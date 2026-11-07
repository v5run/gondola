# Gondola: Compliance, Messaging, Legal & Ops Feasibility

## Verdict
**Buildable for the demo, but two things will break unless you plan for them: (1) Twilio SMS and (2) DoorDash's rules on third parties.** A Twilio trial account cannot send your custom alert text. Every US registration route takes days. DoorDash's terms ban third-party Portal access "through any means", even by an agent the merchant authorizes, and its help article names "using third parties to submit error charge disputes" as a violation. "Draft, merchant submits" is the right line, but the product has to be built around it, not just say it. The other items are low risk if you label them clearly.

## What works
- **Daily close fits the dispute window.** A dispute requires that "the delivery must have occurred within the last 14 days." A nightly check catches every charge in time. Errors reported 72+ hours after delivery are absorbed by DoorDash, so there is nothing to dispute. [DD help]
- **SMS quiet hours (8am–9pm) apply to *telephone solicitations*,** meaning sales pitches. Close-out alerts are informational, and the manager opted in. [SPB]
- **Twilio handles STOP/START/HELP automatically** on long codes and toll-free numbers, and forwards STOP and START to your webhook. [Tw-optout]
- **Video with the mic off is not an "oral communication"** under 18 Pa.C.S. §5702, because that term requires something "uttered". Pennsylvania's all-party consent rule (§5703/§5704(4)) covers audio. Filming shelves is not intercepting anyone's communication. [5702, Ambient]
- **Anthropic API:** "Anthropic may not train models on Customer Content from Services." [Anthropic CT]
- **SendGrid** trial: 100 emails/day for 60 days, no card needed. That is plenty for a demo. [SG pricing]

## Where it fails / risks (ranked)
1. **HIGH: SMS demo can fail on stage.**
   - Trial accounts: "Custom message bodies… aren't available during trial. You must use Twilio-provided templates." Limits: 5 verified recipients, 30-day expiry, sign-up country only. [Tw-trial] Trial messages start with "Sent from a Twilio Trial account" [Tw-trial2]. You can't send the custom alert text at all.
   - US 10DLC requires a paid account. Costs: brand $4.50 (sole prop/low-volume) or $46 (standard), campaign vetting $15, then $2–10/month. Vetting takes "up to 5 business days". [Tw-fees, Tw-vet]
   - Toll-free numbers are blocked until verified, which takes about 3–5 business days. [Tw-TF]
   - The ISV model: a SaaS that messages for its customers must register *each customer* as a brand through the ISV API. That is a real cost for each production tenant. [Tw-10DLC]
   - **Canada:** domestic long codes show no provisioning or registration step and support two-way SMS [Tw-CA]. One provider says numbers acquired after Mar 26, 2025 need A2P registration or "persona verification" [Telerivet]. That conflicts with Twilio's page, so treat it as unverified. **Canada→US traffic requires 10DLC registration** [Aloware], so US judges' phones will not get texts from a Canadian number.
2. **HIGH: DoorDash ToS, and the dispute UI may not need your "draft".**
   - No Portal login, scraping, browser automation or credential sharing by Gondola. Calling unauthorized APIs carries "$100 in liquidated damages for each unauthorized API call." [DD-sec]
   - The real dispute flow is: tick items, choose a reason from a dropdown, submit. Only Admin/Store Manager users can do it, and high dispute volume can disable the button for up to 72h. [DD help] A free-text "drafted dispute" may have nowhere to go. The useful output is a checklist: order #, items, suggested reason, and evidence.
   - Data-use limits on Report Builder exports: **I couldn't find any published terms.** Assume merchant data can't be shared with third parties unless the merchant uploads it.
3. **MEDIUM: Gemini free tier.** On unpaid services, "human reviewers may read, annotate, and process your API input and output", and Google says "Do not submit sensitive, confidential, or personal information to the Unpaid Services." Paid services don't use prompts to improve products. [Gemini terms] Hackathon API keys are often free tier. DoorDash exports can contain customer names, and cash counts contain staff names.
4. **MEDIUM: Retention story.** The IRS says keep business records 3 years generally, employment tax records 4 years, and 6–7 years in some cases. [IRS] Gondola isn't the system of record (the POS and DoorDash statements are). But deleting PDFs after 30 days while calling them the "Daily Close Report" invites the question "where's my cash-variance record from March?" Cash counts and drawer variances may exist *only* in Gondola.
5. **LOW-MED: Consent/CTIA hygiene.** Carriers expect documented opt-in, an immediate confirmation that explains opt-out, and STOP handling. Opt-out rates above 0.5%/24h trigger audits. [Bandwidth] Twilio's Canada guidance: "Only communicate during an end-user's daytime hours unless it is urgent." [Tw-CA] HELP is not forwarded to your webhook by default [Tw-optout]. After STOP, Twilio blocks all sends, so the Ask agent goes silent. CASL (Canada) was not researched; get counsel before launch.
6. **LOW: SendGrid deliverability.** A Gmail single sender gets a warning that it "might fail a DMARC check" [SG-sender], so reports can land in spam. The trial ends at 60 days, and then sending stops. [SG trial]
7. **LOW: Video.** Phone recorders capture audio by default, so "mic off" has to be enforced in code. Filming coworkers in break areas raises privacy expectations; signage is best practice. [Ambient]
8. **LOW: PCI.** Out of scope only if you never ingest card data. Some POS exports include card fields, so validate uploads. (I couldn't fetch the PCI SSC FAQ.)

## Fixes
- **SMS demo plan (today):** upgrade Twilio (about $20 of credit). Buy a **Canadian local number** and text teammates' **Canadian** mobiles, which skips US registration. Send a test from the venue a day early. Also **start toll-free verification now** as a parallel bet, and build an **on-screen SMS simulator** fallback (Twilio Virtual Phone or your own thread UI). Do not promise judges a text to their US phones.
- Production SMS: register as an ISV on 10DLC or verified toll-free. Opt-in screen, confirmation text, HELP reply, monthly reminder. Only "urgent" texts after 10pm; everything else goes in the morning digest. Route STOP/HELP before the Ask agent.
- **DoorDash:** data comes only from merchant-uploaded CSVs. Output is a "Dispute checklist" (order #, items, reason from DoorDash's own list, evidence, days left of 14) plus a deep link. The merchant clicks Dispute. Rate-limit suggestions to avoid the 72h lockout. In the pitch: "Gondola never touches your DoorDash login."
- **LLMs:** paid Gemini (or Vertex) or Claude API only. Strip customer PII and keep it out of prompts; send aggregates and order IDs.
- **Retention:** say "Gondola is not your accounting system of record; the emailed PDF is your copy." Add an export or "keep reports 3 yrs" toggle (GCS Archive storage costs pennies). Keep cash-count line items with the 365-day metrics.
- **Email:** authenticate a $10 domain in SendGrid (DNS CNAMEs) before the event.
- **Video:** `getUserMedia({audio:false})`, plus strip any audio track server-side (`ffmpeg -an`). Show a "No audio recorded" badge. Tell the closer to film shelves, not people.

## Sources
- [DD help] https://help.doordash.com/en-us/merchants/article/what-are-order-error-adjustments
- [DD-sec] https://help.doordash.com/en-us/legal/article/mx-security-terms
- [Tw-trial] https://www.twilio.com/docs/messaging/guides/how-to-use-your-free-trial-account
- [Tw-trial2] https://support.twilio.com/hc/en-us/articles/360036052753
- Trial and toll-free limits: https://support.twilio.com/hc/en-us/articles/11853148778523-Trial-Limits-and-US-Toll-Free-Number-Restrictions
- [Tw-fees] https://support.twilio.com/hc/en-us/articles/1260803965530
- [Tw-vet] https://support.twilio.com/hc/en-us/articles/11587910480155-A2P-10DLC-Campaign-Vetting-FAQ
- [Tw-10DLC] https://www.twilio.com/docs/messaging/compliance/a2p-10dlc
- [Tw-TF] https://support.twilio.com/hc/en-us/articles/5377174717595
- [Tw-CA] https://twilio.com/guidelines/ca/sms
- [Tw-optout] https://support.twilio.com/hc/en-us/articles/223134027-Twilio-Support-for-Opt-Out-Keywords-SMS-STOP-Filtering
- [Aloware] https://support.aloware.com/en/articles/9735661-a2p-10dlc-rules-for-canadian-traffic
- [Telerivet] https://www.telerivet.com/blog/canada-sms-compliance-casl-10dlc-registration
- [SPB] https://www.squirepattonboggs.com/insights/publications/no-calls-during-tcpa-quiet-hours-unless-you-consent/
- [Bandwidth] https://www.bandwidth.com/support/en/articles/12823213
- [SG trial] https://support.sendgrid.com/hc/en-us/articles/35270136965403
- [SG pricing] https://www.twilio.com/en-us/pricing/email-api
- [SG-sender] https://www.twilio.com/docs/sendgrid/ui/sending-email/sender-verification.md
- [5702] https://law.justia.com/codes/pennsylvania/2010/title-18/chapter-57/5702/
- [Ambient] https://www.ambient.ai/learn/pennsylvania-video-surveillance-laws
- [IRS] https://irs.gov/businesses/small-businesses-self-employed/how-long-should-i-keep-records
- [Gemini terms] https://ai.google.dev/gemini/terms
- [Anthropic CT] https://www.anthropic.com/legal/commercial-terms
