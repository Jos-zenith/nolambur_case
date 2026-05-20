import { create } from 'zustand'

import type { MuleGraphPayload, MulePulseAlert } from '@/lib/mule-data'

type PredictionHop = {
  id: string
  label: string
  prob: number
  amount?: number
  geoMismatch?: boolean
}

interface MuleStore {
  graphData: MuleGraphPayload | null
  selectedNodeId: string | null
  alerts: MulePulseAlert[]
  predictionsByNodeId: Record<string, PredictionHop[]>
  graphStatus: 'idle' | 'loading' | 'ready' | 'error'
  graphError: string | null
  setGraphData: (graphData: MuleGraphPayload) => void
  setSelectedNodeId: (nodeId: string | null) => void
  setAlerts: (alerts: MulePulseAlert[]) => void
  setPredictionsByNodeId: (predictionsByNodeId: Record<string, PredictionHop[]>) => void
  setGraphStatus: (status: MuleStore['graphStatus']) => void
  setGraphError: (message: string | null) => void
}

export const useMuleStore = create<MuleStore>(set => ({
  graphData: null,
  selectedNodeId: null,
  alerts: [],
  predictionsByNodeId: {},
  graphStatus: 'idle',
  graphError: null,
  setGraphData: graphData => set({ graphData, graphStatus: 'ready', graphError: null }),
  setSelectedNodeId: selectedNodeId => set({ selectedNodeId }),
  setAlerts: alerts => set({ alerts }),
  setPredictionsByNodeId: predictionsByNodeId => set({ predictionsByNodeId }),
  setGraphStatus: graphStatus => set({ graphStatus }),
  setGraphError: graphError => set({ graphError }),
}))

export type { PredictionHop }