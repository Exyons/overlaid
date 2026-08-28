import { useEffect, useState } from 'react'
import { Library } from './Library'
import { Viewer } from './Viewer'

/** Routing is one piece of state: the open project, mirrored into the URL hash
 *  so reload and the back button behave. A router library would be more code
 *  than this for exactly two screens. */
export default function App() {
  const [open, setOpen] = useState<string | null>(
    () => window.location.hash.slice(1) || null,
  )

  useEffect(() => {
    const sync = () => setOpen(window.location.hash.slice(1) || null)
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])

  const go = (id: string | null) => {
    window.location.hash = id ?? ''
    setOpen(id)
  }

  return open
    ? <Viewer id={open} onBack={() => go(null)} />
    : <Library onOpen={(id) => go(id)} />
}
