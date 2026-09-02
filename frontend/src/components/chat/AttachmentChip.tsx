import { FileText, X } from 'lucide-react'

interface Attachment {
  url: string
  mime: string
  name?: string
  text?: string
}

interface AttachmentChipProps {
  attachment: Attachment
  onRemove: () => void
  className?: string
  imageClassName?: string
  containerClassName?: string
}

export function AttachmentChip({
  attachment,
  onRemove,
  className = 'group relative',
  imageClassName = 'size-16 rounded-lg border border-zinc-700 object-cover',
  containerClassName = 'flex h-16 items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-800 px-3 text-xs text-zinc-300',
}: AttachmentChipProps) {
  if (attachment.mime.startsWith('image/')) {
    return (
      <div className={className}>
        <img
          src={attachment.url}
          alt="attachment"
          className={imageClassName}
        />
        <button
          type="button"
          onClick={onRemove}
          className="absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full bg-red-600 text-white opacity-0 transition-opacity pointer-coarse:opacity-100 group-hover:opacity-100"
        >
          <X className="size-3" />
        </button>
      </div>
    )
  }

  return (
    <div className={className}>
      <div className={containerClassName}>
        <FileText className="size-4 shrink-0 text-indigo-400" />
        <span className="truncate">{attachment.name}</span>
      </div>
      <button
        type="button"
        onClick={onRemove}
        className="absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full bg-red-600 text-white opacity-0 transition-opacity pointer-coarse:opacity-100 group-hover:opacity-100"
      >
        <X className="size-3" />
      </button>
    </div>
  )
}