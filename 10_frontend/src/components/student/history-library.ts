export type StudentHistoryLibraryStatus = 'created' | 'in_progress' | 'completed' | 'terminal'

export interface StudentHistoryLibraryItem {
  key: string
  kind: string
  ref: string
  status: StudentHistoryLibraryStatus
  statusLabel: string
  category: string
  title: string
  poster: string
  dateLabel?: string
  activityLabel?: string
  actionLabel?: string
  actionSize?: 'sm' | 'md'
  actionVariant?: 'primary' | 'secondary'
  actionDisabled?: boolean
}
