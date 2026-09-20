import type { Severity } from "./common"

export type SlaPolicy = {
  priority: Severity
  acknowledgeMinutes: number
  resolveMinutes: number
}
