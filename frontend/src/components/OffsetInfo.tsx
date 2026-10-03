import { ExternalLink, ShieldCheck } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { asArray, fmt, type OffsetInfoPayload } from "@/lib/payloads";

export function OffsetInfo({ payload }: { payload: OffsetInfoPayload }) {
  const standards = asArray(payload.standards);

  return (
    <Card className="w-full max-w-xl">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <ShieldCheck className="size-4" aria-hidden="true" />
          Offsetting your trip
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {typeof payload.return_trip_tonnes === "number" && (
          <p>
            Return trip: <span className="font-semibold">≈{fmt(payload.return_trip_tonnes, 1)} t CO2e</span>
            {payload.indicative_cost_eur?.low !== undefined && (
              <span className="block text-xs text-muted-foreground">
                Verified credits: roughly €{fmt(payload.indicative_cost_eur.low)}–€{fmt(payload.indicative_cost_eur.high)}
                {payload.indicative_cost_eur.per_tonne_low !== undefined &&
                  ` (€${fmt(payload.indicative_cost_eur.per_tonne_low)}–€${fmt(payload.indicative_cost_eur.per_tonne_high)} per tonne)`}
                . Indicative only.
              </span>
            )}
          </p>
        )}
        {payload.lower_carbon_alternative && (
          <p className="rounded-md bg-emerald-50 p-2 text-xs text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">
            Reduce first: switching to {payload.lower_carbon_alternative} avoids most of this before any offset.
          </p>
        )}
        {asArray(payload.principles).length > 0 && (
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {asArray(payload.principles).map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}
        {standards.length > 0 && (
          <div>
            <h2 className="mb-1 text-xs font-medium text-muted-foreground">Standards with public registries</h2>
            <ul className="space-y-1 text-xs">
              {standards.map((s) => (
                <li key={s.name}>
                  {s.registry_url ? (
                    <a
                      href={s.registry_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex items-center gap-1 font-medium underline underline-offset-2"
                    >
                      {s.name} <ExternalLink className="size-3" aria-hidden="true" />
                      <span className="sr-only">(registry, opens in a new tab)</span>
                    </a>
                  ) : (
                    <span className="font-medium">{s.name}</span>
                  )}
                  {s.notes && <span className="text-muted-foreground"> · {s.notes}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
