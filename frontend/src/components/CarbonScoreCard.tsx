/**
 * Colour-coded carbon comparison for one journey (payload type "carbon_card",
 * see src/lib/payloads.ts).
 *
 * - Headline: the mode the user asked about (or the lowest-carbon one).
 * - Comparison list: every mode the action compared, lowest first, each with
 *   its band shown as colour + icon + word.
 * - Red alert: only when the payload carries `alert` (headline mode is red).
 * - ⓘ explainer: a disclosure button (aria-expanded/aria-controls) that the
 *   headline figure also references via aria-describedby, so screen readers
 *   can reach the explanation of "kg CO2e" and the bands.
 */
import { useId, useState } from "react";
import { AlertTriangle, Info } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { BandBadge } from "@/components/BandBadge";
import { BAND_META } from "@/lib/bands";
import { asArray, fmt, isBand, type CarbonScoreCardPayload } from "@/lib/payloads";

export function CarbonScoreCard({ payload }: { payload: CarbonScoreCardPayload }) {
  const [showInfo, setShowInfo] = useState(false);
  const infoId = useId();
  const band = isBand(payload.band) ? payload.band : "amber";
  const meta = BAND_META[band];
  const options = asArray(payload.options);

  return (
    <div className="flex w-full max-w-md flex-col gap-2">
      <Card className={`border ${meta.surface}`}>
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-sm font-medium">
              {payload.mode ?? "Your trip"}
              {payload.route && (
                <span className="block text-xs font-normal text-foreground/75">
                  {payload.route}
                  {typeof payload.distance_km === "number" && ` · ${fmt(payload.distance_km)} km`}
                </span>
              )}
            </CardTitle>
            <BandBadge band={band} />
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-baseline gap-2">
            <p className={`text-2xl font-semibold ${meta.text}`} aria-describedby={payload.tooltip ? infoId : undefined}>
              {fmt(payload.kg_co2e, 1)} <span className="text-sm font-normal">kg CO2e per person</span>
            </p>
            {payload.tooltip && (
              <button
                type="button"
                className="rounded-full text-foreground/75 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                aria-expanded={showInfo}
                aria-controls={infoId}
                aria-label="What do these numbers mean?"
                onClick={() => setShowInfo((v) => !v)}
              >
                <Info className="size-4" aria-hidden="true" />
              </button>
            )}
          </div>
          {payload.tooltip && (
            <p id={infoId} hidden={!showInfo} className="rounded-md bg-background/70 p-2 text-xs text-foreground/75">
              {payload.tooltip}
            </p>
          )}

          {payload.summary && <p className="text-sm">{payload.summary}</p>}

          {payload.is_example && (
            <p className="text-xs font-medium text-foreground/75">
              Example distance: tell me where you're travelling from for your own numbers.
            </p>
          )}

          {options.length > 0 && (
            <div>
              <h2 className="mb-1 text-xs font-medium text-foreground/75">All options, lowest first</h2>
              <ul className="space-y-1">
                {options.map((o, i) => (
                  <li key={`${o.mode}-${i}`} className="flex items-center justify-between gap-2 rounded-md bg-background/60 px-2 py-1 text-sm">
                    <span className="min-w-0 truncate">{o.mode ?? "Option"}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="tabular-nums">{fmt(o.kg_co2e, 1)} kg</span>
                      <BandBadge band={o.band} short />
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {payload.source && (
            <p className="text-xs text-foreground/75">Source: {payload.source}. Rounded averages.</p>
          )}
        </CardContent>
      </Card>

      {payload.alert && (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" aria-hidden="true" />
          <AlertTitle>High-emission option</AlertTitle>
          <AlertDescription>{payload.alert.replace(/^High-emission option\.\s*/, "")}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
