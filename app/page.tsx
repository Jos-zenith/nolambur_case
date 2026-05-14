import { ArrowUpRight, BrainCircuit, Code2, Database, FileCode2, Layers3, LayoutDashboard, ServerCog, ShieldCheck, Sparkles, Workflow } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const metrics = [
  { label: 'Annual loss target', value: '₹22,495 Cr' },
  { label: 'NPCI registry size', value: '23.05 L accounts' },
  { label: 'Mule accounts (case)', value: '40+ accounts' },
]

const steps = [
  {
    index: 'Step 1',
    title: 'Backend',
    eyebrow: 'Graph DB Setup',
    description: 'Neo4j + transaction nodes',
    active: true,
  },
  {
    index: 'Step 2',
    title: 'ML',
    eyebrow: 'T-GNN Model',
    description: 'PyTorch Geometric training',
  },
  {
    index: 'Step 3',
    title: 'API',
    eyebrow: 'FastAPI Bridge',
    description: 'Inference → Next.js',
  },
  {
    index: 'Step 4',
    title: 'Frontend',
    eyebrow: 'Dashboard UI',
    description: 'Mule Pulse live view',
  },
]

const setupSteps = [
  {
    number: '1',
    title: 'Install Neo4j + seed schema',
    description:
      'Model UPI transactions as a directed graph. Each account becomes a node, and each transfer becomes an edge with amount and timestamp metadata.',
    code: `# docker-compose.yml (local dev)
neo4j:
  image: neo4j:5.18
  environment:
    NEO4J_AUTH: neo4j/password
  ports: ["7474:7474", "7687:7687"]`,
  },
  {
    number: '2',
    title: 'Define Cypher schema',
    description:
      'Create unique accounts and attach transfer edges with amount, timestamp, and UPI reference fields for time-aware traversal.',
    code: `CREATE CONSTRAINT account_id IF NOT EXISTS
FOR (a:Account) REQUIRE a.id IS UNIQUE;

MERGE (a:Account {id: $sender})
MERGE (b:Account {id: $receiver})
CREATE (a)-[:TRANSFER {
  amount: $amount,
  ts: $timestamp,
  upi_ref: $ref
}]->(b)`,
  },
  {
    number: '3',
    title: 'Ingest NPCI suspect registry',
    description:
      'Seed suspect accounts as graph nodes so the T-GNN layer can score known mule patterns before the next transfer lands.',
    code: `# bulk_import.py
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))

with driver.session() as s:
    s.run("UNWIND $rows AS r "
          "MERGE (a:Account {id:r.id}) "
          "SET a.suspect=true, a.reason=r.reason",
          rows=suspect_rows)`,
  },
]

const p1Cards = [
  {
    badge: 'P1-A · Cryptography',
    title: 'ZKP Freeze Bridge',
    description: 'Circom / SnarkyJS',
    icon: ShieldCheck,
  },
  {
    badge: 'P1-B · On-device ML',
    title: 'Edge Biometric AI',
    description: 'TensorFlow Lite duress detection',
    icon: BrainCircuit,
  },
  {
    badge: 'P1-C · Integration',
    title: '1930 Auto-Report API',
    description: 'CFCFRMS direct hook',
    icon: Workflow,
  },
]

const techTags = ['Neo4j 5.x', 'Python neo4j driver', 'Cypher', 'Docker']

export default function Home() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(239,68,68,0.12),_transparent_28%),radial-gradient(circle_at_top_right,_rgba(249,115,22,0.1),_transparent_24%),linear-gradient(180deg,#050505_0%,#0a0a0a_40%,#090909_100%)] text-foreground">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-6 sm:px-6 lg:px-8">
        <section className="space-y-6">
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.28em] text-muted-foreground">
                Operation Nolambur — Dev Roadmap
              </p>
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {metrics.map(metric => (
              <Card key={metric.label} className="border-border/60 bg-card/80 shadow-[0_0_0_1px_rgba(255,255,255,0.02)]">
                <CardContent className="px-5 py-4">
                  <p className="text-sm text-muted-foreground">{metric.label}</p>
                  <p className="mt-2 text-3xl font-semibold tracking-tight text-foreground">{metric.value}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <div className="flex items-center gap-3">
            <Badge className="rounded-full bg-destructive/20 px-3 py-1 text-sm font-medium text-destructive-foreground">
              P0 — Now
            </Badge>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-[2rem]">T-GNN Detection Pipeline</h2>
          </div>

          <div className="grid gap-4 md:grid-cols-4">
            {steps.map(step => (
              <Card
                key={step.index}
                className={[
                  'border-border/60 bg-card/80 transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/60 hover:bg-card',
                  step.active ? 'ring-1 ring-primary/80 shadow-[0_0_0_1px_rgba(59,130,246,0.2)]' : '',
                ].join(' ')}
              >
                <CardContent className="space-y-3 px-5 py-5">
                  <p className="text-sm text-muted-foreground">{step.index} · {step.title}</p>
                  <div>
                    <p className="text-xl font-semibold text-foreground">{step.eyebrow}</p>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">{step.description}</p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <Card className="border-border/60 bg-card/80">
            <CardHeader className="space-y-3 border-b border-border/60 pb-5">
              <CardTitle className="text-2xl font-semibold">Step 1 — Graph Database Setup (Neo4j)</CardTitle>
              <div className="inline-flex w-fit items-center gap-2 rounded-md bg-amber-500/20 px-3 py-1 text-sm text-amber-200">
                <Sparkles className="h-4 w-4" />
                Start here — everything else depends on the graph
              </div>
            </CardHeader>
            <CardContent className="space-y-6 pt-6">
              {setupSteps.map(step => (
                <article key={step.number} className="space-y-3">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/20 text-sm font-semibold text-primary">
                      {step.number}
                    </div>
                    <div className="space-y-2">
                      <h3 className="text-lg font-medium text-foreground">{step.title}</h3>
                      <p className="max-w-4xl text-sm leading-6 text-muted-foreground">{step.description}</p>
                    </div>
                  </div>

                  <div className="overflow-hidden rounded-xl border border-border/60 bg-[#161616] shadow-inner">
                    <pre className="max-h-60 overflow-auto p-5 text-sm leading-6 text-zinc-200">
                      <code>{step.code}</code>
                    </pre>
                  </div>
                </article>
              ))}

              <div className="flex flex-wrap gap-2 pt-1">
                {techTags.map(tag => (
                  <Badge key={tag} variant="secondary" className="bg-secondary/30 text-secondary-foreground">
                    {tag}
                  </Badge>
                ))}
              </div>

              <div className="pt-2">
                <Button asChild className="h-11 rounded-xl px-5">
                  <a href="#p1-section">
                    Ask for full code
                    <ArrowUpRight className="h-4 w-4" />
                  </a>
                </Button>
              </div>
            </CardContent>
          </Card>
        </section>

        <section id="p1-section" className="space-y-4 border-t border-border/60 pt-2">
          <div className="flex items-center gap-3">
            <Badge className="rounded-full bg-amber-500/20 px-3 py-1 text-sm font-medium text-amber-200">P1 — Next</Badge>
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">ZKP Bridge + Edge Biometric AI</h2>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            {p1Cards.map(card => {
              const Icon = card.icon
              return (
                <Card key={card.title} className="border-border/60 bg-card/80 transition-all hover:-translate-y-0.5 hover:border-primary/50">
                  <CardContent className="space-y-4 px-5 py-5">
                    <p className="text-sm text-muted-foreground">{card.badge}</p>
                    <div className="flex items-start justify-between gap-4">
                      <div className="space-y-2">
                        <h3 className="text-xl font-semibold text-foreground">{card.title}</h3>
                        <p className="text-sm text-muted-foreground">{card.description}</p>
                      </div>
                      <div className="rounded-xl border border-border/60 bg-secondary/20 p-3 text-primary">
                        <Icon className="h-5 w-5" />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.35fr_0.65fr]">
            <Card className="border-border/60 bg-card/80">
              <CardHeader className="space-y-2 border-b border-border/60 pb-5">
                <CardTitle className="text-xl">Phase Objectives</CardTitle>
                <p className="text-sm text-muted-foreground">
                  The next release hardens the pipeline with proof-based freeze flows, on-device duress scoring, and the 1930 reporting hook.
                </p>
              </CardHeader>
              <CardContent className="space-y-4 pt-5">
                {[
                  { title: 'P1-A', body: 'Compile the Circom circuit and expose a verification endpoint for instant-freeze certificates.' },
                  { title: 'P1-B', body: 'Ship a TensorFlow Lite stress model that runs locally before high-value transfer approval.' },
                  { title: 'P1-C', body: 'Connect the 1930 workflow so confirmed mule clusters can auto-file case details.' },
                ].map(item => (
                  <div key={item.title} className="rounded-xl border border-border/60 bg-secondary/15 p-4">
                    <p className="text-sm font-semibold text-primary">{item.title}</p>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.body}</p>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card className="border-border/60 bg-card/80">
              <CardHeader className="space-y-2 border-b border-border/60 pb-5">
                <CardTitle className="text-xl">Delivery Stack</CardTitle>
                <p className="text-sm text-muted-foreground">Smallest viable backend slices for the first integration pass.</p>
              </CardHeader>
              <CardContent className="space-y-3 pt-5 text-sm text-muted-foreground">
                <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-secondary/15 p-3">
                  <Database className="h-4 w-4 text-primary" />
                  Neo4j graph ingestion
                </div>
                <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-secondary/15 p-3">
                  <ServerCog className="h-4 w-4 text-primary" />
                  Python T-GNN service
                </div>
                <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-secondary/15 p-3">
                  <Code2 className="h-4 w-4 text-primary" />
                  Next.js inference bridge
                </div>
                <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-secondary/15 p-3">
                  <Layers3 className="h-4 w-4 text-primary" />
                  Dashboard telemetry surface
                </div>
                <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-secondary/15 p-3">
                  <LayoutDashboard className="h-4 w-4 text-primary" />
                  Pilot reporting UI
                </div>
                <div className="flex items-center gap-3 rounded-xl border border-border/60 bg-secondary/15 p-3">
                  <FileCode2 className="h-4 w-4 text-primary" />
                  Implementation guide sync
                </div>
              </CardContent>
            </Card>
          </div>
        </section>
      </div>
    </main>
  )
}
