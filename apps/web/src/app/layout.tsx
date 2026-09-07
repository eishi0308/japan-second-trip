import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "@/styles/globals.css";
import { DemoBanner } from "@/components/DemoBanner";

export const metadata: Metadata = {
  title: {
    default: "Japan Second Trip — verified regional travel intelligence",
    template: "%s · Japan Second Trip",
  },
  description:
    "Choose the right next Japan — and make sure the trip actually works. Region decisions and itinerary checks for repeat visitors, grounded in verified evidence.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#fbfaf8",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-paper">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-ink-900 focus:px-4 focus:py-2 focus:text-paper"
        >
          Skip to content
        </a>
        <SiteHeader />
        <DemoBanner />
        <main id="main">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}

function SiteHeader() {
  return (
    <header className="sticky top-0 z-40 border-b border-ink-200/80 bg-paper/85 backdrop-blur-sm">
      <div className="shell flex h-16 items-center justify-between gap-6">
        <Link href="/" className="group flex items-baseline gap-2.5">
          <span className="font-serif text-[1.12rem] tracking-tight text-ink-900">Japan Second Trip</span>
          <span className="hidden text-[0.7rem] uppercase tracking-[0.16em] text-ink-400 sm:inline">
            regional intelligence
          </span>
        </Link>
        <nav aria-label="Main" className="flex items-center gap-1 text-sm">
          <Link href="/where-next" className="btn-ghost">
            Where next
          </Link>
          <Link href="/route-check" className="btn-ghost">
            RouteCheck
          </Link>
          <Link href="/admin" className="btn-ghost hidden sm:inline-flex">
            Admin
          </Link>
        </nav>
      </div>
    </header>
  );
}

function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-ink-200 py-10">
      <div className="shell flex flex-col gap-3 text-[0.82rem] text-ink-500 sm:flex-row sm:items-center sm:justify-between">
        <p>
          Japan Second Trip — a decision-support tool, not a booking agent. Confirm operational details
          with the operator before you pay for anything.
        </p>
        <div className="flex gap-4">
          <Link href="/where-next" className="hover:text-ink-800">
            Where next
          </Link>
          <Link href="/route-check" className="hover:text-ink-800">
            RouteCheck
          </Link>
        </div>
      </div>
    </footer>
  );
}
