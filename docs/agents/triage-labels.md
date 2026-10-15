# Triage labels

The canonical triage roles map one-to-one onto label strings on this repo's GitHub issues.

| Role | Label |
| --- | --- |
| needs-triage | `needs-triage` |
| needs-info | `needs-info` |
| ready-for-agent | `ready-for-agent` |
| ready-for-human | `ready-for-human` |
| wontfix | `wontfix` |

Labels added by the feature loop:

| Label | Meaning |
| --- | --- |
| `feature` | A feature spec; the parent issue of its tickets |
| `ticket` | One vertical slice of a feature, built by one implementer |
| `in-progress` | An implementer is working on this ticket now |
| `audit` | Found by the audit loop; with `ticket` it is a fix, with `needs-info` it waits on the user, alone it is a minor finding |

Labels added for this learning repo:

| Label | Meaning |
| --- | --- |
| `learn` | Lalit types it from code Claude writes and explains in chat, to learn the concept; always with `ready-for-human` |
| `glue` | Plumbing or a repeat of a learned pattern; the feature loop builds it; always with `ready-for-agent` |
