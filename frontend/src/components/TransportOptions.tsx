import { Bus, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BandBadge } from "@/components/BandBadge";
import { asArray, fmt, type TransportOptionsPayload } from "@/lib/payloads";

const KIND_LABELS: Record<string, string> = {
  rail: "rail stations",
  metro: "metro stops",
  tram: "tram stops",
  bus: "bus stops",
  ferry: "ferry piers",
  bike_share: "bike-share docks",
};

export function TransportOptions({ payload }: { payload: TransportOptionsPayload }) {
  const counts = Object.entries(payload.local_transit?.counts ?? {}).sort((a, b) => b[1] - a[1]);
  const routes = asArray(payload.routes);
  if (counts.length === 0 && routes.length === 0) {
    return (
      <p className="max-w-md text-sm text-muted-foreground">
        I don't have public-transport data for {payload.destination ?? "this destination"} yet.
      </p>
    );
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Bus className="size-4" aria-hidden="true" />
          Getting around{payload.destination ? ` ${payload.destination}` : ""}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {counts.length > 0 && (
          <div>
            <h2 className="mb-1 text-xs font-medium text-muted-foreground">
              Within {fmt(payload.local_transit?.radius_km, 1)} km of the centre
            </h2>
            <ul className="flex flex-wrap gap-1.5">
              {counts.map(([kind, n]) => (
                <li key={kind} className="rounded-md bg-muted px-2 py-0.5 text-xs">
                  {n} {KIND_LABELS[kind] ?? kind.replace(/_/g, " ")}
                </li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-muted-foreground">
              Stop locations from {payload.local_transit?.source ?? "OpenStreetMap"}; no live timetables.
            </p>
          </div>
        )}

        {counts.length === 0 && (
          <p className="text-xs text-muted-foreground">No local stop data for {payload.destination ?? "this city"} yet.</p>
        )}

        {routes.length > 0 && (
          <div>
            <h2 className="mb-1 text-xs font-medium text-muted-foreground">Day trips, best match first</h2>
            <ol className="space-y-1">
              {routes.map((r, i) => (
                <li key={`${r.route}-${r.mode}-${i}`} className="flex items-center justify-between gap-2 rounded-md bg-muted/50 px-2 py-1">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{r.mode}</span>
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      {r.route}
                      {typeof r.duration_hours === "number" && (
                        <>
                          <span className="sr-only">, </span>
                          <Clock className="ml-1 size-3" aria-hidden="true" />
                          {fmt(r.duration_hours, 1)} h
                        </>
                      )}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2 text-xs">
                    <span className="tabular-nums">{fmt(r.kg_co2e, 1)} kg</span>
                    <BandBadge band={r.band} short />
                  </span>
                </li>
              ))}
            </ol>
            {payload.routes_note && <p className="mt-1 text-xs text-muted-foreground">{payload.routes_note}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
