"use client";

import { useQuery } from "@tanstack/react-query";
import { createPhotoCreditsQueryOptions } from "@/queryOptions/createConfigQueryOptions";
import { PhotoCredit } from "@/types/config";

const LICENSE_NAMES: Record<string, string> = {
  cc0: "CC0",
  pdm: "Public Domain Mark",
  by: "CC BY",
};

function licenseLabel(credit: PhotoCredit): string {
  const name = LICENSE_NAMES[credit.license] ?? credit.license.toUpperCase();
  return credit.license_version && credit.license !== "pdm"
    ? `${name} ${credit.license_version}`
    : name;
}

function ExternalLink({ href, children }: { href: string | null; children: React.ReactNode }) {
  if (!href) return <>{children}</>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-purple-600 underline-offset-4 hover:underline dark:text-purple-400"
    >
      {children}
    </a>
  );
}

export default function CreditsPage() {
  const { data: credits, isLoading, isError } = useQuery(createPhotoCreditsQueryOptions());

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <h1 className="mb-2 text-2xl font-bold">Photo credits</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        Most demo listings show their sellers&apos; own photos. These listings use openly licensed
        photos found through <ExternalLink href="https://openverse.org">Openverse</ExternalLink>,
        resized for the site.
      </p>
      {isLoading && <p className="text-sm text-muted-foreground">Loading credits…</p>}
      {isError && <p className="text-sm text-red-500">Couldn&apos;t load the photo credits.</p>}
      {credits && credits.length === 0 && (
        <p className="text-sm text-muted-foreground">No photo credits to show.</p>
      )}
      {credits && credits.length > 0 && (
        <ul className="divide-y rounded-lg border">
          {credits.map((credit) => (
            <li key={credit.listing_key} className="px-4 py-3 text-sm">
              <p className="font-medium">{credit.listing_title}</p>
              <p className="text-muted-foreground">
                <ExternalLink href={credit.source_url}>
                  {credit.photo_title || "Photo"}
                </ExternalLink>
                {credit.creator && (
                  <>
                    {" "}
                    by <ExternalLink href={credit.creator_url}>{credit.creator}</ExternalLink>
                  </>
                )}
                {", "}
                <ExternalLink href={credit.license_url}>{licenseLabel(credit)}</ExternalLink>
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
