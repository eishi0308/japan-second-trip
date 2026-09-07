import Link from "next/link";

export default function NotFound() {
  return (
    <div className="shell max-w-measure py-24">
      <p className="label mb-3">404</p>
      <h1 className="text-headline font-serif text-ink-900">That analysis doesn&rsquo;t exist</h1>
      <p className="prose-measure mt-3">
        The link may be from a database that has since been reset, or the id may be mistyped. Analyses
        are addressed by an unguessable id and are not listed publicly.
      </p>
      <div className="mt-8 flex gap-3">
        <Link href="/where-next" className="btn-primary">
          Start a new comparison
        </Link>
        <Link href="/" className="btn-secondary">
          Back to the start
        </Link>
      </div>
    </div>
  );
}
