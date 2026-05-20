'use client'

import { useState } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { MulePulseFeed } from '@/components/MulePulseFeed'
import { PredictedHops } from '@/components/PredictedHops'
import BiometricAlert from '@/components/biometric-alert'

export function RightSidebar() {
  const [activeTab, setActiveTab] = useState('pulse')

  return (
    <Card className="flex h-full flex-col border-border/60 bg-card/50 backdrop-blur-sm">
      <CardHeader className="border-b border-border/40 p-4">
        <CardTitle className="text-lg">Detection Intelligence</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-0">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex h-full flex-col">
          <TabsList className="w-full justify-start rounded-none border-b border-border/40 bg-transparent p-2">
            <TabsTrigger
              value="pulse"
              className="data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:bg-transparent"
            >
              Mule Pulse
            </TabsTrigger>
            <TabsTrigger
              value="predictions"
              className="data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:bg-transparent"
            >
              T-GNN Predictions
            </TabsTrigger>
            <TabsTrigger
              value="biometric"
              className="data-[state=active]:border-b-2 data-[state=active]:border-primary data-[state=active]:bg-transparent"
            >
              Biometric
            </TabsTrigger>
          </TabsList>

          <div className="flex-1 overflow-hidden">
            <TabsContent value="pulse" className="m-0 h-full overflow-auto">
              <div className="p-4">
                <MulePulseFeed />
              </div>
            </TabsContent>

            <TabsContent value="predictions" className="m-0 h-full overflow-auto">
              <div className="p-4">
                <PredictedHops />
              </div>
            </TabsContent>

            <TabsContent value="biometric" className="m-0 h-full overflow-auto">
              <div className="p-4">
                <BiometricAlert />
              </div>
            </TabsContent>
          </div>
        </Tabs>
      </CardContent>
    </Card>
  )
}
