import { HeroSection } from '@/components/HeroSection'
import { HowItWorks } from '@/components/HowItWorks'
import { ScamExplainer } from '@/components/ScamExplainer'
import { TrustBar } from '@/components/TrustBar'

export const metadata = {
  title: 'Stop UPI Fraud Before the Money Leaves | Nolambur',
  description: 'Real-time fraud detection using T-GNN, ZKP, and biometric duress analysis. ₹22,495 Cr loss target. 340ms detection.',
}

export default function Home() {
  return (
    <div className="text-foreground">
      <HeroSection />
      <HowItWorks />
      <ScamExplainer />
      <TrustBar />
    </div>
  )
}
