import { OverviewPage } from '@/components/rail/overview'

export const metadata = {
  title: 'Merchant Risk Console',
  description: 'Mule-chain detection for a payment aggregator: a GNN-scored replay of UPI transactions, rule detectors, analyst actions and evidence packs.',
}

export default function Home() {
  return <OverviewPage />
}
