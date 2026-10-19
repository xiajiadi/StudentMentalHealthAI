import type { AdminOverviewDemoData } from '@/components/admin/admin-workspace-preview'

/** Local 4206 preview records. They are not sent to the API. */
const demoClasses: AdminOverviewDemoData['classes'] = [
  { label: '24级1班', students: 28, teachers: 2, isActive: true },
  { label: '24级2班', students: 27, teachers: 2, isActive: true },
  { label: '24级3班', students: 30, teachers: 2, isActive: true },
  { label: '24级4班', students: 26, teachers: 2, isActive: true },
  { label: '24级5班', students: 29, teachers: 2, isActive: true },
  { label: '24级6班', students: 31, teachers: 2, isActive: true },
  { label: '24级7班', students: 25, teachers: 2, isActive: true },
  { label: '24级8班', students: 28, teachers: 2, isActive: true },
]

const demoOperations: AdminOverviewDemoData['operations'] = [
  { offset: -13, accounts: 1, tasks: 0, classes: 0 },
  { offset: -12, accounts: 1, tasks: 1, classes: 0 },
  { offset: -11, accounts: 2, tasks: 0, classes: 1 },
  { offset: -10, accounts: 0, tasks: 1, classes: 0 },
  { offset: -9, accounts: 3, tasks: 0, classes: 1 },
  { offset: -8, accounts: 1, tasks: 1, classes: 0 },
  { offset: -7, accounts: 0, tasks: 1, classes: 0 },
  { offset: -6, accounts: 2, tasks: 0, classes: 1 },
  { offset: -5, accounts: 1, tasks: 2, classes: 0 },
  { offset: -4, accounts: 2, tasks: 1, classes: 1 },
  { offset: -3, accounts: 1, tasks: 1, classes: 0 },
  { offset: -2, accounts: 2, tasks: 2, classes: 1 },
  { offset: -1, accounts: 2, tasks: 1, classes: 0 },
  { offset: 0, accounts: 2, tasks: 2, classes: 1 },
]

export const createAdminOverviewDemoData = (): AdminOverviewDemoData => ({
  classes: demoClasses.map((item) => ({ ...item })),
  accounts: { students: 224, teachers: 18, pendingActivation: 12 },
  operations: demoOperations.map((item) => ({ ...item })),
})
