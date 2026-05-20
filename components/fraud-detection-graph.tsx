'use client'

import { useEffect, useRef } from 'react'
import * as d3 from 'd3'

interface Node {
  id: string
  type: 'victim' | 'layer1' | 'layer2' | 'beneficiary'
  label: string
  risk?: number
  amount?: number
}

interface Link {
  source: string
  target: string
  amount: number
  velocity: number
  timestamp: string
}

const mockData = {
  nodes: [
    { id: 'victim-01', type: 'victim', label: 'Victim (Digital Arrest)', risk: 0 },
    { id: 'mule-01', type: 'layer1', label: 'MU-0047 (Haridwar)', risk: 95, amount: 2350000 },
    { id: 'mule-02', type: 'layer1', label: 'MU-0051 (Jaipur)', risk: 92, amount: 1820000 },
    { id: 'mule-03', type: 'layer1', label: 'MU-0089 (Rohtak)', risk: 88, amount: 1570000 },
    { id: 'agg-01', type: 'layer2', label: 'AG-0012 (Consolidator)', risk: 97, amount: 6740000 },
    { id: 'agg-02', type: 'layer2', label: 'AG-0019 (Dispatcher)', risk: 94, amount: 4510000 },
    { id: 'beneficiary-01', type: 'beneficiary', label: 'Final Beneficiary', risk: 100 },
  ] as Node[],
  links: [
    { source: 'victim-01', target: 'mule-01', amount: 500000, velocity: 0.3, timestamp: '2024-01-15T14:23:00Z' },
    { source: 'victim-01', target: 'mule-02', amount: 500000, velocity: 0.28, timestamp: '2024-01-15T14:24:15Z' },
    { source: 'victim-01', target: 'mule-03', amount: 500000, velocity: 0.25, timestamp: '2024-01-15T14:25:30Z' },
    { source: 'mule-01', target: 'agg-01', amount: 450000, velocity: 0.8, timestamp: '2024-01-15T14:28:00Z' },
    { source: 'mule-02', target: 'agg-01', amount: 380000, velocity: 0.82, timestamp: '2024-01-15T14:29:45Z' },
    { source: 'mule-03', target: 'agg-02', amount: 420000, velocity: 0.79, timestamp: '2024-01-15T14:31:20Z' },
    { source: 'agg-01', target: 'beneficiary-01', amount: 830000, velocity: 0.95, timestamp: '2024-01-15T14:35:00Z' },
    { source: 'agg-02', target: 'beneficiary-01', amount: 420000, velocity: 0.93, timestamp: '2024-01-15T14:36:15Z' },
  ] as Link[],
}

export default function FraudDetectionGraph() {
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    if (!svgRef.current) return

    const width = svgRef.current.clientWidth
    const height = svgRef.current.clientHeight

    // Clear previous content
    d3.select(svgRef.current).selectAll("*").remove()

    // Create SVG with groups
    const svg = d3.select(svgRef.current)
      .attr('width', width)
      .attr('height', height)

    const defs = svg.append('defs')

    // Add gradients for links
    defs.append('linearGradient')
      .attr('id', 'linkGradient')
      .attr('x1', '0%').attr('y1', '0%')
      .attr('x2', '100%').attr('y2', '100%')
      .selectAll('stop')
      .data([
        { offset: '0%', color: '#ef4444' },
        { offset: '100%', color: '#f97316' },
      ])
      .enter()
      .append('stop')
      .attr('offset', (d: any) => d.offset)
      .attr('stop-color', (d: any) => d.color)

    // Create force simulation
    const simulation = d3.forceSimulation(mockData.nodes as any)
      .force('link', d3.forceLink(mockData.links as any)
        .id((d: any) => d.id)
        .distance(100)
        .strength(0.1))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(40))

    const g = svg.append('g')

    // Draw links
    const link = g.append('g')
      .selectAll('line')
      .data(mockData.links)
      .enter()
      .append('line')
      .attr('stroke', 'url(#linkGradient)')
      .attr('stroke-width', (d: any) => Math.sqrt(d.amount / 100000) * 2)
      .attr('opacity', 0.6)
      .attr('stroke-linecap', 'round')

    // Draw nodes
    const node = g.append('g')
      .selectAll('circle')
      .data(mockData.nodes as any)
      .enter()
      .append('circle')
      .attr('r', (d: any) => {
        switch (d.type) {
          case 'victim': return 20
          case 'layer1': return 18
          case 'layer2': return 22
          case 'beneficiary': return 20
          default: return 16
        }
      })
      .attr('fill', (d: any) => {
        switch (d.type) {
          case 'victim': return '#60a5fa'
          case 'layer1': return '#ef4444'
          case 'layer2': return '#f97316'
          case 'beneficiary': return '#8b5cf6'
          default: return '#6b7280'
        }
      })
      .attr('stroke', '#1a1a1a')
      .attr('stroke-width', 2)
      .call(drag(simulation))

    // Add labels
    const labels = g.append('g')
      .selectAll('text')
      .data(mockData.nodes as any)
      .enter()
      .append('text')
      .attr('font-size', '11px')
      .attr('fill', '#e5e7eb')
      .attr('text-anchor', 'middle')
      .attr('pointer-events', 'none')
      .attr('dy', '0.3em')
      .text((d: any) => {
        const parts = d.label.split(' ')
        return parts.slice(0, 2).join(' ')
      })

    // Add risk badges for high-risk nodes
    node.append('title')
      .text((d: any) => `${d.label}\nRisk: ${d.risk}%${d.amount ? `\nAmount: ₹${(d.amount / 100000).toFixed(1)}L` : ''}`)

    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y)

      node
        .attr('cx', (d: any) => d.x)
        .attr('cy', (d: any) => d.y)

      labels
        .attr('x', (d: any) => d.x)
        .attr('y', (d: any) => d.y)
    })

    function drag(simulation: any) {
      function dragstarted(event: any) {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        event.subject.fx = event.subject.x
        event.subject.fy = event.subject.y
      }

      function dragged(event: any) {
        event.subject.fx = event.x
        event.subject.fy = event.y
      }

      function dragended(event: any) {
        if (!event.active) simulation.alphaTarget(0)
        event.subject.fx = null
        event.subject.fy = null
      }

      return d3.drag<SVGCircleElement, any>()
        .on('start', dragstarted)
        .on('drag', dragged)
        .on('end', dragended)
    }

    return () => {
      simulation.stop()
    }
  }, [])

  return (
    <svg
      ref={svgRef}
      className="w-full h-full bg-secondary/10 rounded border border-border"
      style={{ background: 'radial-gradient(circle at 20% 50%, rgba(239, 68, 68, 0.05), transparent), radial-gradient(circle at 80% 80%, rgba(249, 115, 22, 0.05), transparent)' }}
    />
  )
}
