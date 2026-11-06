# Pilot proposal (draft for discussion)

**Status:** NammaFixtory has no partnership, agreement or integration with any government body. This is a draft
proposal to request a *demonstration meeting* and, if there is interest, a small authorised pilot.

## Problem
Complaints are handled as separate tickets. The same road section can be repaired and fail again, and the pattern is
hard to see from a list of closed tickets.

## Proposal
Run NammaFixtory for **one or two wards for 3 months**, alongside (not instead of) the existing grievance channel.

| Item | Detail |
|---|---|
| Scope | Potholes, road cracks, blocked drains, waterlogging, garbage |
| Users | Citizens of the pilot wards; 2 to 3 ward officers and 1 engineer as reviewers |
| Data | Photos and locations of reports only; contact details only with consent |
| Integration | None required. Officers receive a dashboard and a CSV; referral to the official channel stays manual unless an authorised API is provided |
| Humans in control | Every classification, duplicate link and repair confirmation is an officer decision |

## What we would measure (no outcome is promised)
* Share of reports with valid location; time to process a report.
* Detector precision/recall on pilot photos; false-duplicate and missed-duplicate rate.
* Number of locations flagged as repeat failures, and whether engineers agree with the flags.
* Officer time spent triaging, and citizen and officer feedback.

## Data protection
Consent for contact data; role-based officer access; audit log; no public display of personal locations; face and
number-plate blurring before any photo is shown publicly; retention and deletion policy agreed with the department;
review against applicable Indian data-protection and IT rules before launch.

## Risks and how they are handled
| Risk | Handling |
|---|---|
| AI mistakes | Confidence shown, human confirmation required, officers can correct the type |
| False duplicates | Suggest-only; both reports kept |
| Over-trust in flags | Flags give reasons; causes are labelled hypotheses |
| Misuse or fake reports | Rate limiting, officer review, audit log (to be built before pilot) |
| Digital exclusion | Tamil + English, voice input, WhatsApp channel (simulator built; live needs Business API access); assisted reporting planned |

## Pathways to explore (potential, not confirmed)
Greater Chennai Corporation demonstration meeting; iTNT Hub and Startup India for mentoring and incubation; City
Innovation Exchange for city problem statements; MeitY programmes through an eligible incubator. Eligibility,
current availability and application rules must be checked with each programme before applying.
