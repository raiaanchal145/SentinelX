import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  type ReactNode,
} from "react"

import type { AlertStatus, AuditEntry, Evidence, Ticket, TicketComment } from "../types"
import { buildSeedData, type SeedData } from "./seed"
import { getSession } from "../lib/auth"

export type StoreState = SeedData

type Action =
  | { type: "ACK_ALERT"; alertId: string; actorName: string }
  | { type: "ASSIGN_ALERT_TO_ME"; alertId: string; userId: string; actorName: string }
  | { type: "DISMISS_ALERT"; alertId: string; reason: string; actorName: string }
  | { type: "RESTORE_ALERT_STATUS"; alertId: string; status: AlertStatus; actorName: string }
  | { type: "ESCALATE_ALERT"; alertId: string; actorName: string }
  | { type: "CREATE_TICKET_FROM_ALERT"; alertId: string; ticket: Ticket; actorName: string }
  | { type: "IT_ACK_TICKET"; ticketId: string; actorName: string }
  | { type: "IT_START_TICKET"; ticketId: string; actorName: string }
  | { type: "IT_TOGGLE_CHECKLIST_ITEM"; ticketId: string; itemId: string; actorName: string }
  | { type: "IT_ADD_EVIDENCE"; ticketId: string; evidence: Evidence; actorName: string }
  | { type: "IT_SUBMIT_FOR_VERIFICATION"; ticketId: string; actorName: string }
  | { type: "IT_ADD_COMMENT"; ticketId: string; comment: TicketComment }
  | { type: "SOC_VERIFY_TICKET"; ticketId: string; actorName: string }
  | { type: "SOC_REOPEN_TICKET"; ticketId: string; reason: string; actorName: string }
  | { type: "ADMIN_REASSIGN_ALERT"; alertId: string; userId: string; actorName: string }
  | { type: "ADMIN_REASSIGN_TICKET"; ticketId: string; userId: string; actorName: string }

let auditCounter = 0

function appendAudit(
  state: StoreState,
  entry: Omit<AuditEntry, "id" | "createdAt">,
): AuditEntry[] {
  auditCounter += 1
  const newEntry: AuditEntry = {
    ...entry,
    id: `audit-live-${auditCounter}`,
    createdAt: new Date().toISOString(),
  }
  return [newEntry, ...state.audit]
}

function reducer(state: StoreState, action: Action): StoreState {
  switch (action.type) {
    case "ACK_ALERT": {
      const alert = state.alerts.find((a) => a.id === action.alertId)
      if (!alert) return state
      return {
        ...state,
        alerts: state.alerts.map((a) =>
          a.id === action.alertId ? { ...a, status: "triaged" } : a,
        ),
        audit: appendAudit(state, {
          organizationId: alert.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "alert.acknowledge",
          targetType: "alert",
          targetId: alert.id,
        }),
      }
    }

    case "ASSIGN_ALERT_TO_ME": {
      const alert = state.alerts.find((a) => a.id === action.alertId)
      if (!alert) return state
      return {
        ...state,
        alerts: state.alerts.map((a) =>
          a.id === action.alertId ? { ...a, assigneeUserId: action.userId } : a,
        ),
        audit: appendAudit(state, {
          organizationId: alert.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "alert.assign",
          targetType: "alert",
          targetId: alert.id,
          details: `assigned to ${action.userId}`,
        }),
      }
    }

    case "DISMISS_ALERT": {
      const alert = state.alerts.find((a) => a.id === action.alertId)
      if (!alert) return state
      return {
        ...state,
        alerts: state.alerts.map((a) =>
          a.id === action.alertId
            ? { ...a, status: "dismissed", dismissReason: action.reason || "Dismissed as false positive" }
            : a,
        ),
        audit: appendAudit(state, {
          organizationId: alert.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "alert.dismiss",
          targetType: "alert",
          targetId: alert.id,
          details: action.reason,
        }),
      }
    }

    case "RESTORE_ALERT_STATUS": {
      const alert = state.alerts.find((a) => a.id === action.alertId)
      if (!alert) return state
      return {
        ...state,
        alerts: state.alerts.map((a) =>
          a.id === action.alertId ? { ...a, status: action.status, dismissReason: null } : a,
        ),
        audit: appendAudit(state, {
          organizationId: alert.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "alert.restore",
          targetType: "alert",
          targetId: alert.id,
          details: `undo -> ${action.status}`,
        }),
      }
    }

    case "ESCALATE_ALERT": {
      const alert = state.alerts.find((a) => a.id === action.alertId)
      if (!alert) return state
      const incidentId = `incident-live-${action.alertId}`
      if (state.incidents.some((i) => i.id === incidentId)) return state

      return {
        ...state,
        alerts: state.alerts.map((a) =>
          a.id === action.alertId ? { ...a, status: "converted", incidentId } : a,
        ),
        incidents: [
          {
            id: incidentId,
            organizationId: alert.organizationId,
            title: alert.title,
            summary: alert.summary,
            severity: alert.severity,
            status: "new",
            primaryAssetId: alert.assetId,
            openedAt: new Date().toISOString(),
            resolvedAt: null,
            assigneeUserId: alert.assigneeUserId,
            alertIds: [alert.id],
          },
          ...state.incidents,
        ],
        incidentTimeline: [
          {
            id: `${incidentId}-t1`,
            incidentId,
            occurredAt: new Date().toISOString(),
            entryType: "created",
            description: `Escalated from alert "${alert.title}".`,
            actorType: "user",
            actorName: action.actorName,
          },
          ...state.incidentTimeline,
        ],
        audit: appendAudit(state, {
          organizationId: alert.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "alert.escalate",
          targetType: "alert",
          targetId: alert.id,
          details: `created ${incidentId}`,
        }),
      }
    }

    case "CREATE_TICKET_FROM_ALERT": {
      const alert = state.alerts.find((a) => a.id === action.alertId)
      if (!alert) return state
      return {
        ...state,
        tickets: [action.ticket, ...state.tickets],
        audit: appendAudit(state, {
          organizationId: alert.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "ticket.create",
          targetType: "ticket",
          targetId: action.ticket.id,
          details: `from ${alert.id}`,
        }),
      }
    }

    case "IT_ACK_TICKET": {
      const ticket = state.tickets.find((t) => t.id === action.ticketId)
      if (!ticket) return state
      return {
        ...state,
        tickets: state.tickets.map((t) =>
          t.id === action.ticketId
            ? { ...t, status: "ACKNOWLEDGED", acknowledgedAt: new Date().toISOString() }
            : t,
        ),
        audit: appendAudit(state, {
          organizationId: ticket.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "ticket.acknowledge",
          targetType: "ticket",
          targetId: ticket.id,
        }),
      }
    }

    case "IT_START_TICKET": {
      const ticket = state.tickets.find((t) => t.id === action.ticketId)
      if (!ticket) return state
      return {
        ...state,
        tickets: state.tickets.map((t) =>
          t.id === action.ticketId ? { ...t, status: "INVESTIGATING" } : t,
        ),
        audit: appendAudit(state, {
          organizationId: ticket.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "ticket.start",
          targetType: "ticket",
          targetId: ticket.id,
        }),
      }
    }

    case "IT_TOGGLE_CHECKLIST_ITEM": {
      const ticket = state.tickets.find((t) => t.id === action.ticketId)
      if (!ticket) return state
      return {
        ...state,
        tickets: state.tickets.map((t) =>
          t.id === action.ticketId
            ? {
                ...t,
                status: t.status === "ACKNOWLEDGED" ? "REMEDIATION" : t.status,
                checklist: t.checklist.map((item) =>
                  item.id === action.itemId ? { ...item, done: !item.done } : item,
                ),
              }
            : t,
        ),
      }
    }

    case "IT_ADD_EVIDENCE": {
      return {
        ...state,
        tickets: state.tickets.map((t) =>
          t.id === action.ticketId ? { ...t, evidence: [...t.evidence, action.evidence] } : t,
        ),
      }
    }

    case "IT_SUBMIT_FOR_VERIFICATION": {
      const ticket = state.tickets.find((t) => t.id === action.ticketId)
      if (!ticket) return state
      return {
        ...state,
        tickets: state.tickets.map((t) =>
          t.id === action.ticketId ? { ...t, status: "VERIFICATION" } : t,
        ),
        audit: appendAudit(state, {
          organizationId: ticket.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "ticket.submit_for_verification",
          targetType: "ticket",
          targetId: ticket.id,
        }),
      }
    }

    case "IT_ADD_COMMENT": {
      return {
        ...state,
        tickets: state.tickets.map((t) =>
          t.id === action.ticketId ? { ...t, comments: [...t.comments, action.comment] } : t,
        ),
      }
    }

    case "SOC_VERIFY_TICKET": {
      const ticket = state.tickets.find((t) => t.id === action.ticketId)
      if (!ticket) return state
      return {
        ...state,
        tickets: state.tickets.map((t) =>
          t.id === action.ticketId ? { ...t, status: "RESOLVED", reopenReason: null } : t,
        ),
        audit: appendAudit(state, {
          organizationId: ticket.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "ticket.verify",
          targetType: "ticket",
          targetId: ticket.id,
        }),
      }
    }

    case "SOC_REOPEN_TICKET": {
      const ticket = state.tickets.find((t) => t.id === action.ticketId)
      if (!ticket) return state
      return {
        ...state,
        tickets: state.tickets.map((t) =>
          t.id === action.ticketId
            ? { ...t, status: "REMEDIATION", reopenReason: action.reason }
            : t,
        ),
        audit: appendAudit(state, {
          organizationId: ticket.organizationId,
          actorType: "user",
          actorName: action.actorName,
          action: "ticket.reopen",
          targetType: "ticket",
          targetId: ticket.id,
          details: action.reason,
        }),
      }
    }

    case "ADMIN_REASSIGN_ALERT": {
      const alert = state.alerts.find((a) => a.id === action.alertId)
      if (!alert) return state
      return {
        ...state,
        alerts: state.alerts.map((a) =>
          a.id === action.alertId ? { ...a, assigneeUserId: action.userId } : a,
        ),
        audit: appendAudit(state, {
          organizationId: alert.organizationId,
          actorType: "admin",
          actorName: action.actorName,
          action: "alert.reassign",
          targetType: "alert",
          targetId: alert.id,
          details: `reassigned to ${action.userId}`,
        }),
      }
    }

    case "ADMIN_REASSIGN_TICKET": {
      const ticket = state.tickets.find((t) => t.id === action.ticketId)
      if (!ticket) return state
      return {
        ...state,
        tickets: state.tickets.map((t) =>
          t.id === action.ticketId ? { ...t, assignedUserId: action.userId } : t,
        ),
        audit: appendAudit(state, {
          organizationId: ticket.organizationId,
          actorType: "admin",
          actorName: action.actorName,
          action: "ticket.reassign",
          targetType: "ticket",
          targetId: ticket.id,
          details: `reassigned to ${action.userId}`,
        }),
      }
    }

    default:
      return state
  }
}

type StoreContextValue = {
  state: StoreState
  dispatch: React.Dispatch<Action>
}

const StoreContext = createContext<StoreContextValue | null>(null)

function initStore(): StoreState {
  return buildSeedData(getSession())
}

/**
 * Wraps the app once near the root so every dashboard shares the same
 * in-memory session state -- an action taken on /soc is immediately
 * visible on /admin/soc-oversight in the same browser session.
 *
 * TODO: this whole file is the mock substitute for real API calls. Once
 * the backend exposes alert/incident/ticket endpoints, src/lib/data.ts's
 * function signatures stay the same; only their implementation (and this
 * provider) goes away.
 */
export function MockStoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, initStore)
  const value = useMemo(() => ({ state, dispatch }), [state])

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>
}

export function useMockStore() {
  const ctx = useContext(StoreContext)
  if (!ctx) {
    throw new Error("useMockStore must be used within <MockStoreProvider>")
  }
  return ctx
}
