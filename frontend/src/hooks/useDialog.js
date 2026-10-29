import { useEffect } from 'react'

export function useDialog(dialog) {
  useEffect(() => {
    const opener = document.activeElement
    const element = dialog.current
    element.showModal()
    return () => {
      element.close()
      if (opener?.isConnected && !opener.disabled) opener.focus()
      else document.getElementById('files-heading')?.focus()
    }
  }, [dialog])
}

