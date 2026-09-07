import Link from "next/link";
import { api } from "@/lib/api";
import type { PricingPlan } from "@/lib/types";

export default async function LandingPage() {
  let plans: PricingPlan[] = [];
  try {
    plans = await api.pricing();
  } catch {
    plans = [];
  }

  return (
    <>
      <Hero />
      <HowItWorks />
      <Principles />
      <Pricing plans={plans} />
    </>
  );
}

function Hero() {
  return (
    <section className="shell pb-14 pt-16 sm:pt-24">
      <div className="max-w-3xl animate-in">
        <p className="label mb-5">For repeat visitors to Japan</p>
        <h1 className="text-display font-serif text-ink-900">You&rsquo;ve already done the obvious Japan.</h1>
        <p className="mt-6 max-w-measure text-[1.06rem] leading-relaxed text-ink-700">
          Choose the right next Japan — and make sure the trip actually works.
        </p>
        <p className="prose-measure mt-4">
          Tohoku, Nagano, Hokuriku, Shikoku and Kyushu all exist. The hard part is knowing which one
          fits <em>this</em> trip: your dates, your nights, where you fly in and out, whether you&rsquo;ll
          drive. And then whether the itinerary you&rsquo;ve drafted survives contact with the last bus
          of the day.
        </p>

        <div className="mt-9 flex flex-col gap-3 sm:flex-row">
          <Link href="/where-next" className="btn-primary">
            Where should I go next?
          </Link>
          <Link href="/route-check" className="btn-secondary">
            Check my route
          </Link>
        </div>
      </div>

      <dl className="mt-16 grid gap-x-10 gap-y-8 border-t border-ink-200 pt-10 sm:grid-cols-2 lg:grid-cols-4">
        {[
          {
            title: "Decision support, not a list",
            body: "A ranked comparison with the trade-offs stated. The product will tell you not to go somewhere on this trip.",
          },
          {
            title: "Evidence you can open",
            body: "Every operational claim carries its source, its type, and the date it was last verified.",
          },
          {
            title: "Real transport, not vibes",
            body: "Durations come from verified records or clearly-labelled estimates. Never from a language model.",
          },
          {
            title: "It says when it doesn't know",
            body: "Where sources disagree or a fact has gone stale, a person checks it before you see a number.",
          },
        ].map((item) => (
          <div key={item.title}>
            <dt className="font-serif text-[1.02rem] text-ink-900">{item.title}</dt>
            <dd className="mt-1.5 text-[0.9rem] leading-relaxed text-ink-600">{item.body}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function HowItWorks() {
  const paths = [
    {
      href: "/where-next",
      eyebrow: "Path A",
      title: "I don't know where to go next",
      steps: [
        "Tell us the trip: dates, nights, in and out, how you like to travel",
        "Every region is scored against your constraints by a fixed rubric",
        "Regions that can't work are ruled out, with the constraint named",
        "The survivors are compared, with evidence and trade-offs",
      ],
      cta: "Start with the trip",
    },
    {
      href: "/route-check",
      eyebrow: "Path B",
      title: "I already have a route. Check it.",
      steps: [
        "Paste the itinerary as you'd write it to a friend, or enter stops",
        "Places are resolved and every hop is costed with real transport data",
        "A rules engine grades travel burden, churn, connections and closures",
        "You get the problems, what's already working, and a costed alternative",
      ],
      cta: "Check an itinerary",
    },
  ];

  return (
    <section className="border-t border-ink-200 bg-white py-16">
      <div className="shell">
        <div className="grid gap-10 lg:grid-cols-2 lg:gap-14">
          {paths.map((path) => (
            <div key={path.href} className="flex flex-col">
              <p className="label">{path.eyebrow}</p>
              <h2 className="mt-2 text-headline font-serif text-ink-900">{path.title}</h2>
              <ol className="mt-6 space-y-3.5">
                {path.steps.map((step, index) => (
                  <li key={step} className="flex gap-3.5 text-[0.92rem] leading-relaxed text-ink-700">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-ink-300 text-[0.7rem] tabular-nums text-ink-500">
                      {index + 1}
                    </span>
                    {step}
                  </li>
                ))}
              </ol>
              <Link href={path.href} className="btn-secondary mt-8 self-start">
                {path.cta}
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Principles() {
  return (
    <section className="shell py-16">
      <p className="label mb-3">How it decides</p>
      <h2 className="max-w-2xl text-headline font-serif text-ink-900">
        The parts that must be right are not left to a language model.
      </h2>
      <div className="mt-9 grid gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
        {[
          {
            k: "Deterministic code",
            v: "Fit scores, travel load, night counts, route-health severities. Same input, same answer, every time — and you can read the rubric.",
          },
          {
            k: "Verified data & tools",
            v: "Durations, booking lead times, closure windows, last departures. From records with a verification date, or labelled as estimates.",
          },
          {
            k: "Retrieval",
            v: "Access caveats and booking mechanics that resist normalising into columns — found by combined keyword and semantic search.",
          },
          {
            k: "The language model",
            v: "Reads your itinerary, and explains what the deterministic layer found. It cannot change a score or invent a route.",
          },
          {
            k: "A person",
            v: "When approved sources disagree, or a critical fact has gone stale, it goes to a human before it reaches you.",
          },
          {
            k: "Nothing hidden",
            v: "Confidence, assumptions, unknowns and demo-data labels are shown, not buried. Negative findings are not softened.",
          },
        ].map((item) => (
          <div key={item.k} className="border-l border-ink-200 pl-4">
            <p className="font-serif text-[1rem] text-ink-900">{item.k}</p>
            <p className="mt-1.5 text-[0.88rem] leading-relaxed text-ink-600">{item.v}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function Pricing({ plans }: { plans: PricingPlan[] }) {
  if (plans.length === 0) return null;
  return (
    <section className="border-t border-ink-200 bg-white py-16">
      <div className="shell">
        <p className="label mb-3">Pricing</p>
        <h2 className="text-headline font-serif text-ink-900">Pay for the trip you&rsquo;re taking.</h2>
        <div className="mt-9 grid gap-5 md:grid-cols-3">
          {plans.map((plan) => (
            <div
              key={plan.id}
              className={`card flex flex-col p-6 ${plan.highlight ? "border-ink-900 ring-1 ring-ink-900" : ""}`}
            >
              <p className="font-serif text-[1.05rem] text-ink-900">{plan.name}</p>
              <p className="mt-2.5 font-serif text-[1.9rem] tabular-nums text-ink-900">
                {plan.price_aud === 0 ? "Free" : `A$${plan.price_aud}`}
                {plan.price_aud > 0 ? (
                  <span className="ml-1.5 text-[0.8rem] font-sans text-ink-500">{plan.cadence}</span>
                ) : null}
              </p>
              <p className="mt-3 text-[0.88rem] leading-relaxed text-ink-600">{plan.description}</p>
              <ul className="mt-5 flex-1 space-y-2 text-[0.85rem] text-ink-700">
                {plan.features.map((feature) => (
                  <li key={feature} className="flex gap-2.5">
                    <span aria-hidden="true" className="mt-[0.42rem] h-1 w-1 shrink-0 rounded-full bg-accent-600" />
                    {feature}
                  </li>
                ))}
              </ul>
              <Link
                href={plan.id === "route_check" ? "/route-check" : "/where-next"}
                className={`${plan.highlight ? "btn-primary" : "btn-secondary"} mt-6`}
              >
                {plan.cta}
              </Link>
            </div>
          ))}
        </div>
        <p className="mt-6 text-[0.8rem] text-ink-500">
          Prices are a hypothesis under test and configurable server-side. Payment is not wired up in
          demo mode, and no part of this system can book or pay for anything on your behalf.
        </p>
      </div>
    </section>
  );
}
