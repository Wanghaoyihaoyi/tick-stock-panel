import { lazy } from 'react'
import { BookOpen } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'

const Handbook = lazy(() => import('./Handbook'))

const extension: FrontendExtension = {
  id: 'strategy.handbook',
  apiVersion: 1,
  routes: [{ id: 'strategy-handbook', path: '/strategy-handbook', component: Handbook }],
  navigation: [{ id: 'strategy-handbook', routeId: 'strategy-handbook', label: '策略手册', icon: BookOpen, order: 450 }],
}

export default extension
