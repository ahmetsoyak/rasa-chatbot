/**
 * Carousel of places to stay (payload type "hotel_carousel").
 *
 * Greenwashing safeguard: nothing here looks like a verified certification.
 * The verification badge says exactly what the data is:
 *  - "Sample data"          illustrative entry from the curated set; its
 *                           certification name is shown as an example only
 *  - "Unverified OSM tag"   OpenStreetMap carries a user-edited eco tag
 *  - "No eco data"          OSM place without any eco tag
 * Observable indicators (near a tram stop, small scale) are listed as
 * "Proxy:" items, estimated prices get "≈", and over-budget options get a
 * badge rather than being hidden.
 */
import { ExternalLink, Info, Leaf } from "lucide-react";
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
} from "@/components/ui/carousel";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BandBadge } from "@/components/BandBadge";
import { asArray, fmt, type EcoHotel, type HotelCarouselPayload } from "@/lib/payloads";

function VerificationBadge({ hotel }: { hotel: EcoHotel }) {
  switch (hotel.verification) {
    case "sample_data":
      return (
        <Badge variant="outline" className="h-auto whitespace-normal text-left" title="Illustrative example from the sample set, not a verified listing">
          Sample data{hotel.eco_certification ? ` · example label: ${hotel.eco_certification}` : ""}
        </Badge>
      );
    case "unverified_osm_tag":
      return (
        <Badge variant="outline" className="h-auto whitespace-normal text-left" title="Tag added by an OpenStreetMap contributor; not checked against the certifier">
          Unverified OSM tag{hotel.eco_tag ? `: ${hotel.eco_tag}` : ""}
        </Badge>
      );
    default:
      return <Badge variant="outline">No eco data</Badge>;
  }
}

function HotelCard({ hotel, position, total }: { hotel: EcoHotel; position: number; total: number }) {
  const estimate = hotel.price_is_estimate ? "≈" : "";
  const price =
    typeof hotel.price_per_night === "number"
      ? `${estimate}${fmt(hotel.price_per_night)} ${hotel.currency ?? ""} / night`
      : "Price unavailable";

  return (
    <Card className="h-full" role="group" aria-roledescription="slide" aria-label={`${position} of ${total}: ${hotel.name ?? "Place to stay"}`}>
      <CardHeader className="space-y-1 pb-2">
        <CardTitle className="text-sm">{hotel.name ?? "Unnamed place"}</CardTitle>
        <div className="flex flex-wrap gap-1">
          <VerificationBadge hotel={hotel} />
          {hotel.within_budget === false && <Badge variant="outline" className="border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-300">Above budget</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-2 pb-2 text-sm">
        <p>
          <span className="font-medium">{price}</span>
          {hotel.price_is_estimate && (
            <span className="block text-xs text-muted-foreground">
              Estimate for {/^[aeiou]/i.test(hotel.type ?? "") ? "an" : "a"} {hotel.type ?? "place"} of this kind{hotel.price_band ? ` (${hotel.price_band})` : ""}
            </span>
          )}
        </p>
        {asArray(hotel.proxies).length > 0 && (
          <ul className="space-y-0.5 text-xs text-muted-foreground" aria-label={hotel.verification === "sample_data" ? "Listed features" : "Sustainability proxies"}>
            {asArray(hotel.proxies).slice(0, 4).map((p) => (
              <li key={p} className="flex gap-1">
                <Leaf className="mt-0.5 size-3 shrink-0 text-emerald-700 dark:text-emerald-400" aria-hidden="true" />
                <span>{hotel.verification === "sample_data" ? p : `Proxy: ${p}`}</span>
              </li>
            ))}
          </ul>
        )}
        {hotel.description && <p className="text-xs text-muted-foreground">{hotel.description}</p>}
      </CardContent>
      <CardFooter className="flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          {hotel.carbon_is_estimate ? "≈" : ""}
          {fmt(hotel.kg_co2e_per_night)} kg CO2e / night
          <BandBadge band={hotel.band} short />
        </span>
        {hotel.booking_url && (
          <a
            href={hotel.booking_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 underline underline-offset-2"
          >
            Website <ExternalLink className="size-3" aria-hidden="true" />
            <span className="sr-only">(opens in a new tab)</span>
          </a>
        )}
      </CardFooter>
    </Card>
  );
}

export function HotelCarousel({ payload }: { payload: HotelCarouselPayload }) {
  const hotels = asArray(payload.hotels);
  if (hotels.length === 0) return null;

  return (
    <div role="group" className="w-full max-w-3xl space-y-2" aria-label={`Advisor: places to stay${payload.destination ? ` in ${payload.destination}` : ""}`}>
      <Carousel opts={{ align: "start" }} className="w-full">
        <CarouselContent>
          {hotels.map((hotel, i) => (
            <CarouselItem key={hotel.name ?? i} className="basis-4/5 sm:basis-1/2 lg:basis-1/3">
              <HotelCard hotel={hotel} position={i + 1} total={hotels.length} />
            </CarouselItem>
          ))}
        </CarouselContent>
        {hotels.length > 1 && (
          <>
            <CarouselPrevious className="-left-3 size-7" />
            <CarouselNext className="-right-3 size-7" />
          </>
        )}
      </Carousel>
      {payload.note && (
        <p className="flex gap-1.5 text-xs text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          <span>
            {payload.data_source && <span className="font-medium">{payload.data_source}. </span>}
            {payload.note}
          </span>
        </p>
      )}
    </div>
  );
}
