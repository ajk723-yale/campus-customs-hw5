import type { ManagerFields as Fields } from '../api'

interface Props {
  expected: string // what must be typed to confirm
  value: Omit<Fields, 'recorded_by'>
  onChange: (v: Omit<Fields, 'recorded_by'>) => void
  simulatedHelp?: string
}

/** The honesty and confirmation fields every manager action needs. */
export function ManagerFields({ expected, value, onChange, simulatedHelp }: Props) {
  return (
    <div className="mf">
      <label className="mf-check small">
        <input type="checkbox" checked={value.simulated} onChange={(e) => onChange({ ...value, simulated: e.target.checked })} />
        Simulated event <span className="muted">{simulatedHelp ?? '(stands in for a real customer or vendor action in this assignment)'}</span>
      </label>
      <input
        className="mf-basis"
        placeholder="Basis (required): what is this record based on?"
        aria-label="Basis for this record"
        value={value.basis}
        onChange={(e) => onChange({ ...value, basis: e.target.value })}
      />
      <input
        placeholder={`Type ${expected} to confirm`}
        aria-label={`Type ${expected} to confirm`}
        value={value.confirm}
        onChange={(e) => onChange({ ...value, confirm: e.target.value })}
      />
    </div>
  )
}
