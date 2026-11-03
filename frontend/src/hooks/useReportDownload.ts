import { useCallback, useRef, useState } from 'react'
import { apiErrorMessage } from '../services/api'
import { downloadDebateReport } from '../services/debates'

const SAFE_FILENAME = /^[a-zA-Z0-9._-]+\.pdf$/

/**
 * Download the server-rendered PDF report for a debate. The request goes
 * through the shared API client (Authorization header, never a token in the
 * URL); the blob is saved via a temporary object URL that is revoked after
 * the browser has started the download. Duplicate clicks are ignored while a
 * download is in flight.
 */
export function useReportDownload() {
  const [downloadingId, setDownloadingId] = useState<string | null>(null)
  const [error, setError] = useState<{ id: string; message: string } | null>(null)
  const inFlight = useRef(false)

  const download = useCallback(async (debateId: string) => {
    if (inFlight.current) return
    inFlight.current = true
    setDownloadingId(debateId)
    setError(null)
    try {
      const { blob, filename } = await downloadDebateReport(debateId)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      // Prefer the server-provided name (topic slug + debate id); fall back to
      // a stable client-side name if the header is missing or malformed.
      anchor.download =
        filename && SAFE_FILENAME.test(filename)
          ? filename
          : `maves-debate-${debateId.slice(0, 8)}-report.pdf`
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) {
      setError({
        id: debateId,
        message: apiErrorMessage(err, 'The PDF report could not be downloaded.'),
      })
    } finally {
      inFlight.current = false
      setDownloadingId(null)
    }
  }, [])

  return { download, downloadingId, error }
}
