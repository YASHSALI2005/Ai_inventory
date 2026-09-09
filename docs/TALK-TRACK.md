# Talk track — Ma'aden MRO pitch

For presenting `docs/pitch.html` (7 slides). **Target: 10–12 minutes**, leaving room for
questions. Arrow keys advance.

---

## The one sentence to hold in your head

> **"Their storerooms are full and their plants still go down waiting for parts — both true at
> once, in the same building. We can prove which parts are dead money and which are actually at
> risk, and prove it with a number rather than a claim."**

> **Note on the wording.** "Storeroom" is the spare-parts warehouse; "plant" is the production
> machinery. They sit a few hundred metres apart *on the same site.* This is not a distance
> problem — it is a *wrong things stocked* problem. Say it as a contradiction, never as
> geography: *"the wardrobe is stuffed and there is still nothing to wear."*

Everything else is support for that. If you have 30 seconds instead of 10 minutes, say that.

---

## Before you start

**Say what this is, and what it isn't.** Open with:

> "This is Phase 0 — my understanding of the problem and what I propose to build. No code yet.
> I want your go-ahead before I start building, not after."

That framing does two things: it sets expectations so nobody asks "where's the demo," and it
makes the meeting a decision rather than a status update.

---

## Slide 1 — Title & the paradox · *~60 sec*

**Point at the three numbers.**

> "Three numbers frame this whole project.
> Twenty to forty percent of a typical MRO storeroom is excess or obsolete — money frozen in
> parts that will never be issued.
> At the same time, in the same storeroom, ten to fifteen percent of *critical* parts carry
> stockout risk.
> And when one of those critical parts is missing, buying it as an emergency costs three to
> five times a planned purchase.
>
> Full storeroom, empty shelf. Both at once. That's the problem."

**Then the strip at the bottom:**

> "Scope is Ma'aden Aluminium. Two locations. The bauxite mine stands alone in central Arabia,
> and 600 kilometres away on the Gulf coast, the refinery, smelter and rolling mill all sit on
> **one** 20 square kilometre site at Ras Al Khair — the most vertically integrated aluminium
> complex in the world.
>
> That single site is big enough to hold several storerooms of its own. Which turns out to
> matter." *(sets up slide 2)*

⚠️ **Don't** say these are Ma'aden's numbers. They're industry benchmarks. If you blur that
once, everything after it gets doubted.

---

## Slide 2 — A day it goes wrong · *~2 min · SLOW DOWN HERE*

**This is now your most important slide.** It replaces every abstract argument with one story
anyone in the room can picture. Tell it like a story, not like a slide.

**Walk the timeline, one step at a time:**

> "Let me show you an ordinary day at Ras Al Khair.
>
> **Two fourteen in the morning.** A bearing on the rolling mill fails. The line stops.
> Now — nobody made a mistake here. Bearings wear out. This will always happen.
>
> **Two forty.** The planner checks the storeroom. Four hundred metres away. And that bearing
> is not in stock. It was never in stock.
>
> *(pause here)* **That's the failure.** Not the bearing — the fact that it wasn't there.
>
> **Three ten.** Emergency order. Standard lead time is six weeks, so they air-freight it and
> pay three to five times the normal price.
>
> **Three days later** the part lands and the mill restarts. Three days of flat-rolled output
> that they never get back — and that downtime costs far more than the bearing did."

**Now turn to the right-hand panel. This is the turn:**

> "And here's the part that should bother you. While that mill was down — in that *same*
> storeroom, three aisles away — sat four hundred filter cartridges. Three hundred thousand
> riyals' worth. For a filtration unit that was removed in 2019.
>
> Fully stocked. Perfectly counted. Correctly recorded in SAP. And not one of them will ever
> be issued."

**The bottom bar — say this slowly and then stop:**

> "The money to buy that bearing had already been spent. It was sitting on a shelf, three
> aisles away, as something else."

⚠️ **Two things you must say out loud**, both on the slide:
- **"This is not a distance problem."** The store is 400 m from the mill. If you leave this
  out, someone will think the answer is better forklifts.
- **"It's not a counting problem either."** Their stock records were correct. This is not
  about SAP being wrong — it's about the wrong things having been bought.

💡 The bottom-left rail says *"illustrative incident."* If anyone asks, confirm it
immediately: *"That's a representative pattern, not a Ma'aden record — I don't have your
incident data yet."* Volunteering that costs you nothing and buys a lot.

---

## Slide 3 — Where the money leaks · *~2 min*

**Set the frame first — this distinction is what managers actually care about:**

> "That one story repeats across the storerooms in four ways. And they split into two very
> different kinds of money."

**Left panel — the one-time release:**

> "First: capital that's simply frozen. Excess, obsolete, duplicated items — industry
> benchmarks put that at twenty to forty percent of inventory value.
>
> On a five hundred million riyal inventory, that's a hundred to two hundred million riyals
> sitting on shelves. That's a **one-time cash release**. You free it once."

⚠️ **Point at the note in that box and read it:**

> "And I want to be straight with you — the five hundred million is a placeholder, because I
> don't have your inventory value yet. That's one of the questions on my last slide. Put your
> number in and the arithmetic holds."

**Right panel — the recurring bleed. Go top to bottom, quickly:**

> "The other three bleed every single year.
>
> **Downtime** is the biggest, and it's the hardest one to see on any report — because lost
> output in a continuous process never comes back.
>
> **The expedite premium** — three to five times, every emergency purchase, plus freight
> and customs.
>
> **Buying what you already own** — one storeroom purchases a part the storeroom three
> kilometres away is holding idle. Not because three kilometres is far. Because it can't
> *see* it. And the same thing happens across the ex-Alcoa and Alba part numbers.
>
> **And carrying cost** — roughly twenty-five percent a year in storage, handling, insurance
> and write-down, charged on capital that's already trapped."

**The two boxes at the bottom — this is the argument of the whole slide:**

> "Why do these persist? Because every one of them is **invisible in a stock report.** A stock
> report tells you what you have. It doesn't tell you what you *should* have, or what you
> already have somewhere else.
>
> But — and this is the point — each leak leaves a **measurable signature in the data.**
> They're listed there. Stockouts on criticality-A items. The share of POs raised as
> emergencies. Duplicate issues across storage locations. The ageing profile.
>
> And if it has a signature, we can detect it, rank it in riyals, and work through it."

💡 **That last line is the bridge to your whole proposal.** Land it, then move on.

---

## Slide 4 — The same day, with the platform · *~2 min*

**Frame it as the same story, replayed:**

> "Now let me run that exact same day again — same bearing, same storeroom, same two
> fourteen in the morning — with the platform in place."

**Walk down the timeline. The numbered orange stamps are SOW capability numbers:**

> "**Four months earlier**, the system flags this bearing. Not from a hunch — from consumption
> history *plus* the maintenance plan. Criticality A, six-week lead time, and it's due for
> replacement inside the shutdown window. *(that's capability one)*
>
> **Its reorder point gets set from its own behaviour** — its own demand pattern, its own lead
> time, its own consequence of failure. Not a number somebody typed in years ago.
> *(capability three)*
>
> And here's the part I like: **it's paid for with money that was already on the shelf.**
> Funded by writing down those 2019 filters and the duplicates. Not by asking you for new
> budget. *(capability two)*
>
> **Two fourteen.** The bearing fails. Exactly as before — nothing prevents wear.
>
> **Three thirty.** The part is on the shelf. The mill is running again."

**Point at the comparison tiles on the right:**

> "Same incident. Downtime goes from three days to about an hour. The part costs one times
> instead of three to five. The three hundred thousand in dead filters is released instead of
> sitting there. And the whole thing is self-funded."

**Then the dashed box — say this, it's your credibility:**

> "Notice what did *not* change. The failure still happened. And a person still made every
> single decision. The platform didn't run the plant. It changed one thing: **what was on the
> shelf at two forty.**"

**The green bar at the bottom — this is your bridge into slide 5:**

> "So the fix isn't faster reaction. It's a better stocking decision, made four months
> earlier. Which is exactly what the seven capabilities produce — and that's the next slide."

💡 **This is the slide that sells.** Slide 2 makes them feel the problem; this one shows them
the same day with a different ending. Don't rush the pause between "two fourteen — the bearing
fails" and "three thirty — the mill is running."

---

## Slide 5 — What we build · *~2 min*

**Walk the flow left to right — the order is the argument:**

> "The SOW lists seven capabilities. They're not seven separate features — they're a chain,
> and the order matters.
>
> **Four** comes first. Clean the data — negative stock, blank part numbers, missing units of
> measure. Nothing downstream is believable until this is done.
>
> **One** — predict demand. And not just from consumption history: from the maintenance plan
> too. A planned shutdown is a *known* future spike, not a surprise. That's how you buy at
> planned prices instead of expediting at three to five times.
>
> **Three** — turn that into policy. Reorder point and safety stock per item, computed from
> its own demand shape and its own criticality. Not a number someone typed in years ago.
>
> **Two and five** — release the cash. Two finds the dead money. Five says: this site has
> forty units sitting idle while that site is about to buy five. Move it, don't buy it.
>
> **Six** prices the trade-off — 95% service or 98%, here's the cash difference and here's the
> risk you're taking.
>
> **Seven** is the front door. A planner types a plain question and gets an answer."

**Point at the legend:**

> "The filled blocks are what I'd build deep — real algorithms that hold up under expert
> questioning. The rest are real, just narrower for a POC."

**Then the out-of-scope box — say this, don't skip it:**

> "And I want to be explicit about what the POC does *not* do. No writing back into SAP. No
> automatic purchase orders. It reads and recommends — a human decides."

💡 Stating your own limits before you're asked reads as confidence. Skipping it reads as
overselling.

---

## Slide 6 — Architecture · *~90 sec*

**Sweep left to right, don't read every box:**

> "Data flows one direction. Sources on the left, ingestion, then the intelligence, then what
> people actually see."

**Then the two callouts — this is the whole slide:**

> "Two decisions worth your attention.
>
> **First, the adapter layer.** The synthetic data for the POC plugs in behind the same
> interface a real SAP and PiLog connector would use. So when you ask me 'how long before this
> runs on our actual data' — the answer is: replace one layer. Not rebuild it. The POC is
> built to be promoted, not thrown away.
>
> **Second, the AI boundary.** The conversational layer *narrates*. It does not compute. It
> calls the engine, gets a number, and reads it back — always showing the numbers and the item
> list behind the answer.
>
> Because if that thing invents a stock figure once, in front of a planner, they will never
> trust it again."

⚠️ **Flag the dependency honestly** (it's on the bottom rail):

> "One open item: capability one needs maintenance plans and equipment criticality. Those live
> in a CMMS, not in the ERP stock tables. I need to know whether that exists and whether we
> can reach it."

---

## Slide 7 — Road, proof, and the ask · *~2 min*

**Timeline:**

> "Phase 0 is done — that's this. Phase 1 is what I'm asking for: the proof of concept, on
> synthetic data. Phase 2 is a pilot on one site with a real extract, where we replace every
> borrowed benchmark with Ma'aden's own numbers. Then scale, then other business units.
>
> I've deliberately not put dates on these. I'd rather cost the work first than commit to a
> deadline nobody can meet."

**The two proof mechanisms — this is your strongest differentiator:**

> "Now, the part I care most about. Most POCs end with 'it looks good.' I want this one to end
> with a number.
>
> **First** — I hide the problems on purpose. The synthetic data will carry deliberately
> planted defects: duplicates, obsolete spares, negative stock, blank part numbers. And a
> sealed answer key the engine never sees. So at the end I don't say 'it works' — I say 'it
> found 94 of the 100 problems we hid, with 6 false positives.'
>
> **Second** — I replay the recommended stocking policy over three years of history and
> compare it against a conventional min/max baseline on the same data. Same conditions,
> two methods, count the stockout-days."

**The third box — say this deliberately, it buys you a lot:**

> "And one thing I won't do. There's a figure everyone quotes — that 50 to 60 percent of MRO
> inventory is obsolete. I went looking for the study behind it and there isn't one; it traces
> back to consultant estimates. So I've used the conservative 20-to-40 band throughout, and
> everything borrowed is labelled as borrowed."

**The ask — stop talking after this:**

> "So what I'm asking for is approval to build Phase 1. And there are four things I need from
> Ma'aden to sharpen it — the ERP version, whether a CMMS exists, their MRO inventory value
> and SKU count, and whether the Alba and Alcoa material masters have been merged yet."

Then **stop.** Let the silence sit. Don't fill it.

---

## Questions you should expect

**"Why synthetic data? Why not just use real data?"**
> "Two reasons. It removes the data-access delay so I can start now. But more importantly —
> with synthetic data I control the answer key. If I run this on real data I can show you
> pretty screens, but I can't tell you how *accurate* it is, because nobody knows the right
> answer. With planted defects, I can give you a precision and recall number."

**"How is this different from what SAP already does?"**
> "SAP holds the data and applies one safety stock formula across it. The gap is in the
> analysis on top — routing each item to the right method based on its demand behaviour, and
> spotting duplicates across material masters that were never merged. That's not a replacement
> for SAP, it sits on top of it."

**"How long will Phase 1 take?"**
> "I'd rather scope it properly than guess in the room. What I can say is the order: the data
> generator first, because everything is judged against it, then the classifier, then the
> policy engine, then the interface. The conversational layer comes last because it narrates
> what the engine computes." *(If pushed for a number, give a range and label it a range.)*

**"What's the actual saving in SAR?"**
> "I can't tell you honestly until I know two things — their total MRO inventory value and
> their SKU count. Once I have those, the arithmetic is: conservative excess band times
> inventory value, plus the expedite premium on unplanned purchases. I'd rather give you a
> range you can check on the back of an envelope than a precise number you can't."

**"Can the AI just do it automatically? Auto-order?"**
> "Technically yes. I'd advise against it, at least above a value threshold. The POC reads and
> recommends; a human approves. That boundary is what makes planners willing to use it at all."

**"Where exactly are the storerooms?"**
> "Two locations. The mine, and then everything else on one 20 km² site at Ras Al Khair. How
> many storerooms sit inside that site, and whether SAP treats them as separate plants or as
> storage locations under one plant — that's one of the things I need from you. It changes
> whether cross-store visibility is a reporting change or an integration one, and it sets the
> cost tiers for transfer recommendations."

**"If everything is on one site, why would parts go missing?"**
> "Because it isn't a distance problem. The storeroom is 400 metres from the machine. The part
> that's needed simply isn't among the twenty thousand items on those shelves — while three
> aisles over, four hundred filters sit for a unit that was removed in 2019. The wardrobe is
> stuffed and there's still nothing to wear."

**"Why should we believe the AI won't make things up?"**
> "Because it isn't allowed to calculate. It calls the engine, gets a number, and reads it
> back — with the numbers and the item list shown alongside. It's a translator, not a
> calculator."

---

## If you only remember three things

1. **Slide 2, the closing line** — *"The money to buy that bearing had already been spent. It
   was sitting on a shelf, three aisles away, as something else."* This is the whole problem in
   one sentence, and it is the line people will repeat after you leave.
2. **Slide 4, the dashed box** — the failure still happened, and a person still made every
   decision. The platform changed *what was on the shelf at 02:40.* This proves you are not
   overselling AI.
3. **Slide 7, mechanism 1** — planted defects with an answer key. This proves you'll come back
   with a measurement, not a claim.

Everything else is scaffolding around those three.

**If you get cut to two minutes:** slide 2, then slide 7's ask. Nothing else.

---

## Delivery notes

- **Slow down on slides 2, 4 and 7.** Move quickly through 1, 3 and 6.
- **Slides 2 and 4 are one story told twice** — the bad day, then the same day fixed. Tell them
  as a story, with pauses. Do not read the boxes aloud; the room can read.
- **Don't read the slides.** Everything on them is visible; your job is the connective tissue
  between the boxes.
- **Say "I don't know" when you don't.** The open questions on slide 7 exist so you can point
  at them instead of guessing. Guessing an ERP version in front of the people who own it is
  the fastest way to lose the room.
- **Numbers you must not blur:** every percentage on these slides is an industry benchmark,
  not a Ma'aden measurement. Say "industry benchmark" out loud at least twice.
