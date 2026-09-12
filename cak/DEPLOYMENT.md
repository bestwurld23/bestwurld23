# Deployment checklist

Required by PRD §15.4. Nothing in this repository is hard to install; the hard part is
the part below, and skipping it is how a project like this becomes the thing it was
built to oppose.

Running a node in your own organization, for your own community, needs only the technical
section. Everything above it applies when you are deploying **for someone else** — another
jurisdiction, a tribal nation, or another country.

---

## 1. Invitation

**A node is not deployed anywhere without a written invitation from the authority that
owns the civic process there.** Depending on the terrain, that is:

- A county clerk or municipal election board (US local)
- The governing body of a tribal nation — not a federal or state agency speaking for it
- An Electoral Management Body (EMB), for another country

The invitation must name who asked, what they asked for, and who at the host organization
holds the device. Keep it with the deployment record. No invitation, no deployment: not
"we'll get one later", not "a nonprofit partner vouched for us".

- [ ] Written invitation on file, from the right authority
- [ ] Named local steward organization, with a named person responsible
- [ ] The authority has seen the legal banner text and the "I don't know" copy in the
      language residents will read them in

## 2. Data residency

- [ ] Where the device physically lives is written down
- [ ] Where field reports sync to is written down, and it is an endpoint the host chose
      (their KoBo, their MinIO, their ministry server). The default is: nowhere.
- [ ] The project holds **no copy of any voter list**, and no personal data from the
      deployment. This is checkable: `cak.db` has no schema for it, and the node refuses
      to start if a personal-data column appears.

## 3. Legal framing

- [ ] The banner reads, in every language the pack ships: *this device is not an official
      election office; information is copied from published official documents; we cannot
      say if you are eligible to vote.*
- [ ] Steward training covers the §19 copy: **do not interpret ID laws, do not tell anyone
      they cannot vote, hand them the official contact card.**
- [ ] Local counsel has reviewed the deployment where election-administration law is
      restrictive about third-party voter assistance. In some US states, activity near a
      polling place is regulated; find out before the device is in a building.

## 4. Exit clause

The host must be able to eject us and keep running. This is not a courtesy; it is the
thing that makes the rest credible.

- [ ] The host has the node's signing key and can run it with no involvement from us
- [ ] The host has been shown how to fork the repository and build from source
- [ ] The licences (AGPL-3.0 for the node, Apache-2.0 for everything else) have been
      explained, including what a hosted fork owes its users
- [ ] Nothing in the deployment depends on a service we operate — because there isn't one

## 5. Content and language

- [ ] Every file in `official/` came from the authority, with a `*.meta.yaml` sidecar
      recording the source URL, retrieval date and hash
- [ ] Redistribution of those documents is permitted by the authority's terms. If it is
      not, ship the pack empty and have the steward load them from a USB stick on site.
- [ ] At least one language besides English where the community needs it, translated by
      someone who speaks it, not by a machine alone
- [ ] Tribal-language packs are maintained by the nation wherever possible, per PRD §22.4

## 6. Technical

- [ ] `cak-node health` reports `ok`, with the expected file count and pack version
- [ ] `cak-changelog verify --root <pack>` passes, chain and files
- [ ] Steward password set; node bound to localhost or to the LAN *with* a password
- [ ] Disk encryption (LUKS) enabled if the device sits somewhere it can walk away from
- [ ] Paper pack printed and on the table — the kit is not deployed until the paper is
- [ ] SMS codes, if enabled, tested end to end with a real feature phone
- [ ] Steward has done a dry run of a USB update, and knows the verifier catches tampering
- [ ] Steward has passed the "I don't know" exercise in `docs/steward-runbook.md`

## 7. Afterwards

- [ ] A date set to review what residents actually asked and what the node could not
      answer — from counters, never from question text
- [ ] A named way for the steward to reach a human when something breaks during an
      election period
- [ ] An agreed end date or renewal for the deployment, so that a device nobody is
      maintaining does not sit in a library answering questions from a stale pack

---

## What we do not measure

Do not set "votes increased" as a target for a deployment (PRD §16). The confounders are
overwhelming and the incentive it creates is wrong: it turns an information service into a
turnout operation, which is exactly the accusation that gets a project like this thrown
out of a county. If a research partner wants to study turnout effects, they should do so
independently, with their own ethics review.
