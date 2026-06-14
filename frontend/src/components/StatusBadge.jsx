export default function StatusBadge({ status }) {
  const map = {
    unlisted: 'bg-gray-600 text-gray-100',
    active: 'bg-emerald-600 text-white',
    sold: 'bg-blue-600 text-white',
  }
  const cls = map[status] || 'bg-gray-700 text-gray-200'
  return (
    <span className={`inline-block text-xs font-bold uppercase tracking-wide px-2 py-1 rounded ${cls}`}>
      {status || 'unknown'}
    </span>
  )
}
