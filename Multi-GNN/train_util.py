import torch
import tqdm
from torch_geometric.transforms import BaseTransform
from typing import Union
from torch_geometric.data import Data, HeteroData
from torch_geometric.loader import LinkNeighborLoader
from sklearn.metrics import f1_score
import json
import importlib.util


def _has_neighbor_sampler_backend() -> bool:
    return importlib.util.find_spec('pyg_lib') is not None or importlib.util.find_spec('torch_sparse') is not None


class _FullGraphBatchLoader:
    def __init__(self, data, input_ids, edge_label_index, batch_size, shuffle, transform, local_edge_ids=None):
        self.data = data
        self.input_ids = input_ids
        self.edge_label_index = edge_label_index
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.transform = transform
        # The caller (get_loaders) knows how `self.data` was assembled, so it
        # can hand us -- for each seed edge in input_ids order -- the correct
        # position of that same edge within self.data's OWN (locally re-based)
        # edge_attr/EdgeID array. Without this, callers were doing
        # `input_ids[batch.input_id]`, which only happens to be right when
        # input_ids is itself a contiguous arange (e.g. a chronological
        # train split of pre-sorted data); for any other split (random,
        # stratified, or a val split whose data object is offset by the train
        # rows preceding it) that silently looked up the wrong -- or an
        # out-of-range -- row. Defaulting to input_ids preserves old behavior
        # for callers that don't pass this.
        self.local_edge_ids = local_edge_ids if local_edge_ids is not None else input_ids

    def __len__(self):
        if self.input_ids.numel() == 0:
            return 0
        return (self.input_ids.numel() + self.batch_size - 1) // self.batch_size

    def __iter__(self):
        order = torch.randperm(self.input_ids.numel()) if self.shuffle else torch.arange(self.input_ids.numel())
        for start in range(0, order.numel(), self.batch_size):
            batch_positions = order[start:start + self.batch_size]
            batch_local_edge_ids = self.local_edge_ids[batch_positions]

            batch = self.data.clone()
            if isinstance(batch, HeteroData):
                batch['node', 'to', 'node'].edge_label_index = self.edge_label_index[:, batch_positions]
                batch['node', 'to', 'node'].input_id = batch_local_edge_ids
            else:
                batch.edge_label_index = self.edge_label_index[:, batch_positions]
                batch.input_id = batch_local_edge_ids

            if self.transform is not None:
                batch = self.transform(batch)

            yield batch

class AddEgoIds(BaseTransform):
    r"""Add IDs to the centre nodes of the batch.
    """
    def __init__(self):
        pass

    def forward(self, data: Union[Data, HeteroData]):
        x = data.x if not isinstance(data, HeteroData) else data['node'].x
        device = x.device
        ids = torch.zeros((x.shape[0], 1), device=device)
        if not isinstance(data, HeteroData):
            nodes = torch.unique(data.edge_label_index.view(-1)).to(device)
        else:
            nodes = torch.unique(data['node', 'to', 'node'].edge_label_index.view(-1)).to(device)
        ids[nodes] = 1
        if not isinstance(data, HeteroData):
            data.x = torch.cat([x, ids], dim=1)
        else: 
            data['node'].x = torch.cat([x, ids], dim=1)
        
        return data

def extract_param(parameter_name: str, args) -> float:
    """
    Extract the value of the specified parameter for the given model.
    
    Args:
    - parameter_name (str): Name of the parameter (e.g., "lr").
    - args (argparser): Arguments given to this specific run.
    
    Returns:
    - float: Value of the specified parameter.
    """
    file_path = './model_settings.json'
    with open(file_path, "r") as file:
        data = json.load(file)

    return data.get(args.model, {}).get("params", {}).get(parameter_name, None)

def add_arange_ids(data_list):
    '''
    Add the index as an id to the edge features to find seed edges in training, validation and testing.

    Args:
    - data_list (str): List of tr_data, val_data and te_data.
    '''
    for data in data_list:
        if isinstance(data, HeteroData):
            data['node', 'to', 'node'].edge_attr = torch.cat([torch.arange(data['node', 'to', 'node'].edge_attr.shape[0]).view(-1, 1), data['node', 'to', 'node'].edge_attr], dim=1)
            offset = data['node', 'to', 'node'].edge_attr.shape[0]
            data['node', 'rev_to', 'node'].edge_attr = torch.cat([torch.arange(offset, data['node', 'rev_to', 'node'].edge_attr.shape[0] + offset).view(-1, 1), data['node', 'rev_to', 'node'].edge_attr], dim=1)
        else:
            data.edge_attr = torch.cat([torch.arange(data.edge_attr.shape[0]).view(-1, 1), data.edge_attr], dim=1)

def get_loaders(tr_data, val_data, te_data, tr_inds, val_inds, te_inds, transform, args):
    if not _has_neighbor_sampler_backend():
        # val_data was built (in data_loading.get_data) by concatenating tr_inds
        # then val_inds, so its edge_index only spans len(tr_inds)+len(val_inds)
        # edges, re-based to start at 0 -- unlike te_data, which keeps the full,
        # globally-indexed graph. val_inds itself still holds the *original*
        # global positions (needed later to look up each edge's EdgeID for seed
        # masking), so it must not be used directly to slice val_data.edge_index:
        # for any split where val_inds' global positions exceed val_data's
        # length, that raises an out-of-bounds IndexError. The val portion of
        # val_data is always the tail block right after the tr_inds edges.
        val_local_inds = torch.arange(tr_inds.numel(), tr_inds.numel() + val_inds.numel())

        if isinstance(tr_data, HeteroData):
            tr_edge_label_index = tr_data['node', 'to', 'node'].edge_index
            val_edge_label_index = val_data['node', 'to', 'node'].edge_index[:, val_local_inds]
            te_edge_label_index = te_data['node', 'to', 'node'].edge_index[:, te_inds]
        else:
            tr_edge_label_index = tr_data.edge_index
            val_edge_label_index = val_data.edge_index[:, val_local_inds]
            te_edge_label_index = te_data.edge_index[:, te_inds]

        # Correct local EdgeID (position within each loader's own `data` object,
        # matching add_arange_ids' per-object 0-based relabeling) for each seed
        # edge, in the same order as tr_inds/val_inds/te_inds:
        #  - tr_data's rows ARE tr_inds' rows, in that order -> local id == position.
        #  - val_data's rows are [tr_inds' rows][val_inds' rows] (see get_data) ->
        #    val's local ids are offset by len(tr_inds) (this is val_local_inds).
        #  - te_data is the full, globally-ordered graph -> local id == the
        #    original global row number, i.e. te_inds itself.
        tr_local_edge_ids = torch.arange(tr_inds.numel())
        val_local_edge_ids = val_local_inds
        te_local_edge_ids = te_inds

        tr_loader = _FullGraphBatchLoader(tr_data, tr_inds, tr_edge_label_index, args.batch_size, True, transform, local_edge_ids=tr_local_edge_ids)
        val_loader = _FullGraphBatchLoader(val_data, val_inds, val_edge_label_index, args.batch_size, False, transform, local_edge_ids=val_local_edge_ids)
        te_loader = _FullGraphBatchLoader(te_data, te_inds, te_edge_label_index, args.batch_size, False, transform, local_edge_ids=te_local_edge_ids)
        return tr_loader, val_loader, te_loader

    if isinstance(tr_data, HeteroData):
        tr_edge_label_index = tr_data['node', 'to', 'node'].edge_index
        tr_edge_label = tr_data['node', 'to', 'node'].y


        tr_loader =  LinkNeighborLoader(tr_data, num_neighbors=args.num_neighs, 
                                    edge_label_index=(('node', 'to', 'node'), tr_edge_label_index), 
                                    edge_label=tr_edge_label, batch_size=args.batch_size, shuffle=True, transform=transform)
        
        val_edge_label_index = val_data['node', 'to', 'node'].edge_index[:,val_inds]
        val_edge_label = val_data['node', 'to', 'node'].y[val_inds]


        val_loader =  LinkNeighborLoader(val_data, num_neighbors=args.num_neighs, 
                                    edge_label_index=(('node', 'to', 'node'), val_edge_label_index), 
                                    edge_label=val_edge_label, batch_size=args.batch_size, shuffle=False, transform=transform)
        
        te_edge_label_index = te_data['node', 'to', 'node'].edge_index[:,te_inds]
        te_edge_label = te_data['node', 'to', 'node'].y[te_inds]


        te_loader =  LinkNeighborLoader(te_data, num_neighbors=args.num_neighs, 
                                    edge_label_index=(('node', 'to', 'node'), te_edge_label_index), 
                                    edge_label=te_edge_label, batch_size=args.batch_size, shuffle=False, transform=transform)
    else:
        tr_loader =  LinkNeighborLoader(tr_data, num_neighbors=args.num_neighs, batch_size=args.batch_size, shuffle=True, transform=transform)
        val_loader = LinkNeighborLoader(val_data,num_neighbors=args.num_neighs, edge_label_index=val_data.edge_index[:, val_inds],
                                        edge_label=val_data.y[val_inds], batch_size=args.batch_size, shuffle=False, transform=transform)
        te_loader =  LinkNeighborLoader(te_data,num_neighbors=args.num_neighs, edge_label_index=te_data.edge_index[:, te_inds],
                                edge_label=te_data.y[te_inds], batch_size=args.batch_size, shuffle=False, transform=transform)
        
    return tr_loader, val_loader, te_loader

@torch.no_grad()
def evaluate_homo(loader, inds, model, data, device, args):
    '''Evaluates the model performane for homogenous graph data.'''
    preds = []
    ground_truths = []
    for batch in tqdm.tqdm(loader, disable=not args.tqdm):
        #select the seed edges from which the batch was created
        inds = inds.detach().cpu()
        batch_edge_inds = inds[batch.input_id.detach().cpu()]
        batch_edge_ids = loader.data.edge_attr.detach().cpu()[batch_edge_inds, 0]
        mask = torch.isin(batch.edge_attr[:, 0].detach().cpu(), batch_edge_ids)

        #add the seed edges that have not been sampled to the batch
        missing = ~torch.isin(batch_edge_ids, batch.edge_attr[:, 0].detach().cpu())

        if missing.sum() != 0 and (args.data == 'Small_J' or args.data == 'Small_Q'):
            missing_ids = batch_edge_ids[missing].int()
            n_ids = batch.n_id
            add_edge_index = data.edge_index[:, missing_ids].detach().clone()
            node_mapping = {value.item(): idx for idx, value in enumerate(n_ids)}
            add_edge_index = torch.tensor([[node_mapping[val.item()] for val in row] for row in add_edge_index])
            add_edge_attr = data.edge_attr[missing_ids, :].detach().clone()
            add_y = data.y[missing_ids].detach().clone()
        
            batch.edge_index = torch.cat((batch.edge_index, add_edge_index), 1)
            batch.edge_attr = torch.cat((batch.edge_attr, add_edge_attr), 0)
            batch.y = torch.cat((batch.y, add_y), 0)

            mask = torch.cat((mask, torch.ones(add_y.shape[0], dtype=torch.bool)))

        #remove the unique edge id from the edge features, as it's no longer needed
        batch.edge_attr = batch.edge_attr[:, 1:]
        
        with torch.no_grad():
            batch.to(device)
            out = model(batch.x, batch.edge_index, batch.edge_attr)
            out = out[mask]
            pred = out.argmax(dim=-1)
            preds.append(pred)
            ground_truths.append(batch.y[mask])
    pred = torch.cat(preds, dim=0).cpu().numpy()
    ground_truth = torch.cat(ground_truths, dim=0).cpu().numpy()
    f1 = f1_score(ground_truth, pred)

    return f1

@torch.no_grad()
def evaluate_hetero(loader, inds, model, data, device, args):
    '''Evaluates the model performane for heterogenous graph data.'''
    preds = []
    ground_truths = []
    for batch in tqdm.tqdm(loader, disable=not args.tqdm):
        #select the seed edges from which the batch was created
        inds = inds.detach().cpu()
        batch_edge_inds = inds[batch['node', 'to', 'node'].input_id.detach().cpu()]
        batch_edge_ids = loader.data['node', 'to', 'node'].edge_attr.detach().cpu()[batch_edge_inds, 0]
        mask = torch.isin(batch['node', 'to', 'node'].edge_attr[:, 0].detach().cpu(), batch_edge_ids)

        #add the seed edges that have not been sampled to the batch
        missing = ~torch.isin(batch_edge_ids, batch['node', 'to', 'node'].edge_attr[:, 0].detach().cpu())

        if missing.sum() != 0 and (args.data == 'Small_J' or args.data == 'Small_Q'):
            missing_ids = batch_edge_ids[missing].int()
            n_ids = batch['node'].n_id
            add_edge_index = data['node', 'to', 'node'].edge_index[:, missing_ids].detach().clone()
            node_mapping = {value.item(): idx for idx, value in enumerate(n_ids)}
            add_edge_index = torch.tensor([[node_mapping[val.item()] for val in row] for row in add_edge_index])
            add_edge_attr = data['node', 'to', 'node'].edge_attr[missing_ids, :].detach().clone()
            add_y = data['node', 'to', 'node'].y[missing_ids].detach().clone()
        
            batch['node', 'to', 'node'].edge_index = torch.cat((batch['node', 'to', 'node'].edge_index, add_edge_index), 1)
            batch['node', 'to', 'node'].edge_attr = torch.cat((batch['node', 'to', 'node'].edge_attr, add_edge_attr), 0)
            batch['node', 'to', 'node'].y = torch.cat((batch['node', 'to', 'node'].y, add_y), 0)

            mask = torch.cat((mask, torch.ones(add_y.shape[0], dtype=torch.bool)))

        #remove the unique edge id from the edge features, as it's no longer needed
        batch['node', 'to', 'node'].edge_attr = batch['node', 'to', 'node'].edge_attr[:, 1:]
        batch['node', 'rev_to', 'node'].edge_attr = batch['node', 'rev_to', 'node'].edge_attr[:, 1:]
        
        with torch.no_grad():
            batch.to(device)
            out = model(batch.x_dict, batch.edge_index_dict, batch.edge_attr_dict)
            out = out[('node', 'to', 'node')]
            out = out[mask]
            pred = out.argmax(dim=-1)
            preds.append(pred)
            ground_truths.append(batch['node', 'to', 'node'].y[mask])
    pred = torch.cat(preds, dim=0).cpu().numpy()
    ground_truth = torch.cat(ground_truths, dim=0).cpu().numpy()
    f1 = f1_score(ground_truth, pred)

    return f1

def save_model(model, optimizer, epoch, args, data_config):
    # Save the model in a dictionary
    torch.save({
                'epoch': epoch + 1,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict()
                }, f'{data_config["paths"]["model_to_save"]}/checkpoint_{args.unique_name}{"" if not args.finetune else "_finetuned"}.tar')
    
def load_model(model, device, args, config, data_config):
    checkpoint = torch.load(f'{data_config["paths"]["model_to_load"]}/checkpoint_{args.unique_name}.tar')
    model.load_state_dict(checkpoint['model_state_dict'])
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.lr)
    optimizer.load_state_dict(checkpoint['optimizer_state_dict'])

    return model, optimizer