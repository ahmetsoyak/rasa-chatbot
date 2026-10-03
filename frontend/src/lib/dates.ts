/**
 * Travel-date helpers for the date picker. Every choice is normalised to
 * "YYYY-MM-DD to YYYY-MM-DD" before it is sent, so the bot never has to parse
 * relative phrases such as "in 4 days for 5 nights".
 *
 * Dates are handled as local calendar days (no time component) to avoid
 * off-by-one errors around midnight and daylight-saving changes.
 */

export const MAX_NIGHTS = 60;
/** How far ahead a trip may start. */
export const MAX_LEAD_DAYS = 2 * 365;

export interface DateRange {
  start: Date;
  end: Date;
}

export function today(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

/** Whole nights between two calendar days. */
export function nightsBetween(start: Date, end: Date): number {
  const utc = (d: Date) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.round((utc(end) - utc(start)) / 86_400_000);
}

/** Local date as YYYY-MM-DD (the value format of <input type="date">). */
export function toIso(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** Parse YYYY-MM-DD as a local calendar day; null for empty or invalid input. */
export function fromIso(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return null;
  const [y, m, d] = [Number(match[1]), Number(match[2]) - 1, Number(match[3])];
  const date = new Date(y, m, d);
  return date.getFullYear() === y && date.getMonth() === m && date.getDate() === d ? date : null;
}

/** The message sent to the bot. */
export function rangeMessage({ start, end }: DateRange): string {
  return `${toIso(start)} to ${toIso(end)}`;
}

/** Human-readable range, e.g. "Wed 7 Oct – Mon 12 Oct 2026 · 5 nights". */
export function describeRange({ start, end }: DateRange): string {
  const sameYear = start.getFullYear() === end.getFullYear();
  const day = (d: Date, withYear: boolean) =>
    [d.toLocaleDateString("en-GB", { weekday: "short" }), d.getDate(), d.toLocaleDateString("en-GB", { month: "short" }),
     ...(withYear ? [d.getFullYear()] : [])].join(" ");
  const nights = nightsBetween(start, end);
  return `${day(start, !sameYear)} – ${day(end, true)} · ${nights} night${nights === 1 ? "" : "s"}`;
}

/** Short label for chips, e.g. "9–11 Oct" or "30 Oct – 2 Nov". */
export function shortRange({ start, end }: DateRange): string {
  const month = (d: Date) => d.toLocaleDateString("en-GB", { month: "short" });
  return start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear()
    ? `${start.getDate()}–${end.getDate()} ${month(end)}`
    : `${start.getDate()} ${month(start)} – ${end.getDate()} ${month(end)}`;
}

/** Why a range can't be used, or null when it is fine. */
export function rangeProblem(range: DateRange | null, now: Date = today()): string | null {
  if (!range) return "Choose a start and an end date.";
  if (nightsBetween(now, range.start) < 0) return "The trip can't start in the past.";
  if (nightsBetween(now, range.start) > MAX_LEAD_DAYS) return "That start date is more than two years away.";
  const nights = nightsBetween(range.start, range.end);
  if (nights < 1) return "The end date must be after the start date.";
  if (nights > MAX_NIGHTS) return `Trips can be at most ${MAX_NIGHTS} nights.`;
  return null;
}

/** "Start in `inDays` days, stay `nights` nights." */
export function relativeRange(inDays: number, nights: number, now: Date = today()): DateRange {
  const start = addDays(now, inDays);
  return { start, end: addDays(start, nights) };
}

export interface DatePreset {
  id: string;
  label: string;
  range: DateRange;
}

/**
 * One-tap suggestions. A weekend is Friday to Sunday; on Saturday "this
 * weekend" starts today, and on Sunday it is no longer offered.
 */
export function datePresets(now: Date = today()): DatePreset[] {
  const dow = now.getDay(); // 0 = Sunday
  const friday = addDays(now, dow === 6 ? -1 : dow === 0 ? -2 : 5 - dow);
  const sunday = addDays(friday, 2);
  const presets: DatePreset[] = [];

  const thisWeekend = { start: nightsBetween(now, friday) < 0 ? now : friday, end: sunday };
  if (nightsBetween(thisWeekend.start, thisWeekend.end) >= 1) {
    presets.push({ id: "this-weekend", label: `This weekend (${shortRange(thisWeekend)})`, range: thisWeekend });
  }
  const nextWeekend = { start: addDays(friday, 7), end: addDays(sunday, 7) };
  presets.push({ id: "next-weekend", label: `Next weekend (${shortRange(nextWeekend)})`, range: nextWeekend });
  const nextMonth = relativeRange(30, 7, now);
  presets.push({ id: "week-next-month", label: `A week next month (${shortRange(nextMonth)})`, range: nextMonth });
  return presets;
}
