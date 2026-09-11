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

        <div className="mt-9 flex flex-col gap-3 sm:flex-row">
          <Link href="/where-next" className="btn-primary">
            Where should I go next?
          </Link>
          <Link href="/route-check" className="btn-secondary">
            Check my route
          </Link>
        </div>
      </div>

      <ul className="mt-16 grid gap-x-10 gap-y-5 border-t border-ink-200 pt-10 sm:grid-cols-2 lg:grid-cols-4">
        {[
          "Decision support, not a list",
          "Evidence you can open",
          "Real transport, not vibes",
          "It says when it doesn't know",
        ].map((item) => (
          <li key={item} className="font-serif text-[1.02rem] leading-snug text-ink-900">
            {item}
          </li>
        ))}
      </ul>
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
        "Tell us the trip",
        "Every region scored by a fixed rubric",
        "Impossible regions ruled out, constraint named",
        "The survivors compared, with evidence",
      ],
      cta: "Start with the trip",
    },
    {
      href: "/route-check",
      eyebrow: "Path B",
      title: "I already have a route. Check it.",
      steps: [
        "Paste the itinerary, or enter stops",
        "Every hop costed with real transport data",
        "Travel burden, churn and closures graded",
        "Problems, strengths, and a costed alternative",
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
          { k: "Deterministic code", v: "Scores and severities. Same input, same answer." },
          { k: "Verified data & tools", v: "Durations and booking rules, with a verification date." },
          { k: "Retrieval", v: "Access caveats, by keyword and semantic search." },
          { k: "The language model", v: "Explains. It cannot change a score or invent a route." },
          { k: "A person", v: "Stale or conflicting facts go to a human first." },
          { k: "Nothing hidden", v: "Confidence, assumptions and unknowns are shown." },
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
