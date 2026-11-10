import Dropzone from './Dropzone'

interface Props {
  file: File | null
  preview: string | null
  onFile: (file: File) => void
  onClear: () => void
  label?: string
  hint?: string
}

/** Body photo picker (own body upload and staff avatar upload): dropzone, then a preview with "choose another". */
export default function PhotoPicker({ preview, onFile, onClear, label = 'Tana rasmini tanlang yoki bu yerga tashlang', hint = 'JPG, PNG — max 20 MB' }: Props) {
  if (!preview) return <Dropzone onFile={onFile} accept="image/jpeg,image/png" label={label} hint={hint} />
  return (
    <div style={{ marginBottom: 20 }}>
      <img
        src={preview}
        alt="Tanlangan rasm"
        style={{
          width: '100%', maxHeight: 400, objectFit: 'contain', borderRadius: 'var(--radius-md)',
          background: 'var(--inset)', marginBottom: 12,
        }}
      />
      <button className="btn btn-secondary btn-sm" onClick={onClear}>Boshqa rasm tanlash</button>
    </div>
  )
}
