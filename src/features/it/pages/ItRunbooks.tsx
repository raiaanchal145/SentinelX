import Badge from "../../../components/ui/Badge"

/** Static reference runbooks (P15 keeps them static on purpose -- the
 * content is curated, not generated, and none of it drives behavior).
 * Labelled as reference so nobody mistakes them for live workflow. */
const RUNBOOKS = [
  {
    title: "Credential reset after suspected compromise",
    when: "Alert or incident naming a user account with successful auth from a new device or country.",
    steps: [
      "Confirm the account with the ticket's linked incident (shared entries only).",
      "Disable the account or force a password reset through your identity provider.",
      "Revoke active sessions and API tokens for the account.",
      "Check for mail-rule or MFA-method changes made in the window.",
      "Record what you did as checklist tasks and attach the change log as evidence.",
    ],
  },
  {
    title: "Patch out-of-date public-facing service",
    when: "Ticket created from a vulnerability or exposure finding on an internet-facing asset.",
    steps: [
      "Take the host out of the serving path or rate-limit exposure first.",
      "Apply the vendor patch in a maintenance window.",
      "Restart the service and verify the version from the vendor's own reporting.",
      "Re-run the detection that raised the finding and attach its output.",
    ],
  },
  {
    title: "Isolate a workstation with active malware",
    when: "Ticket linked to an incident with endpoint telemetry showing execution.",
    steps: [
      "Network-quarantine the machine (keep EDR management traffic alive).",
      "Collect the triage package before reimaging.",
      "Reimage or clean to the standard of your EDR vendor's guidance.",
      "Rotate any credentials used from that machine.",
    ],
  },
]

function ItRunbooks() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-fg-primary">Runbooks</h1>
        <p className="mt-0.5 flex items-center gap-2 text-xs text-fg-muted">
          Reference procedures only -- adapt them to your environment.
          <Badge tone="neutral">Reference</Badge>
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {RUNBOOKS.map((runbook) => (
          <section key={runbook.title} className="rounded-card border border-line bg-surface p-4">
            <h2 className="text-sm font-semibold text-fg-primary">{runbook.title}</h2>
            <p className="mt-1 text-xs text-fg-muted">{runbook.when}</p>
            <ol className="mt-3 list-decimal space-y-1.5 pl-4 text-xs text-fg-secondary">
              {runbook.steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </section>
        ))}
      </div>
    </div>
  )
}

export default ItRunbooks
