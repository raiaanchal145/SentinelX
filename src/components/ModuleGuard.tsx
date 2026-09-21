import type { ReactNode } from "react"
import { Navigate } from "react-router-dom"

import { useMe } from "../lib/me"
import type { ModuleKey } from "../lib/modules"
import Skeleton from "./ui/Skeleton"

/**
 * Route-level module guard (Prompt B section C5): a direct URL to a
 * page whose module isn't in the signed-in account's effective_modules
 * shows the no-access (403) state instead of a blank or broken page.
 * Wrap only pages that map to a specific module -- a role's own
 * Overview/home route (see roleNav.ts's `module`-less items) doesn't
 * need this, since it's always reachable for that role.
 */
function ModuleGuard({ module, children }: { module: ModuleKey; children: ReactNode }) {
  const { me, loading } = useMe()

  if (loading) {
    return <Skeleton count={4} className="h-10 w-full" />
  }

  if (!me?.effective_modules || !(module in me.effective_modules)) {
    return <Navigate to="/no-access" replace />
  }

  return <>{children}</>
}

export default ModuleGuard
