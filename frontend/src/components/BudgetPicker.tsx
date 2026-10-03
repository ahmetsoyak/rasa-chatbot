import { useId, useState } from "react";
import { Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Currencies the bot's budget parser recognises by code. */
const CURRENCIES = ["EUR", "GBP", "USD", "CHF", "JPY", "TRY", "ISK"] as const;
type Currency = (typeof CURRENCIES)[number];

const REGION_CURRENCY: Record<string, Currency> = {
  GB: "GBP", US: "USD", CH: "CHF", JP: "JPY", TR: "TRY", IS: "ISK",
};

/** Accommodation ceilings mirror BUDGET_NIGHTLY_CAP_EUR in actions.py. */
const LEVELS = [
  { id: "low", label: "Low", hint: "up to €80/night" },
  { id: "medium", label: "Medium", hint: "€80–160/night" },
  { id: "high", label: "High", hint: "no nightly limit" },
] as const;

const QUICK_AMOUNTS = [500, 1000, 1500, 2500];
const MAX_AMOUNT = 1_000_000;

function defaultCurrency(): Currency {
  const region = typeof navigator !== "undefined" ? navigator.language.split("-")[1]?.toUpperCase() : undefined;
  return (region && REGION_CURRENCY[region]) || "EUR";
}

function formatMoney(amount: number, currency: Currency): string {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);
}

interface BudgetPickerProps {
  /** `message` goes to the bot; `display` is what the user's bubble shows. */
  onSubmit: (message: string, display: string) => void;
  disabled: boolean;
}

/** Quick ways to answer "What's your approximate budget for this trip?". */
export function BudgetPicker({ onSubmit, disabled }: BudgetPickerProps) {
  const ids = useId();
  const [currency, setCurrency] = useState<Currency>(defaultCurrency);
  const [amount, setAmount] = useState<number>(NaN);

  const valid = Number.isFinite(amount) && amount >= 1 && amount <= MAX_AMOUNT;
  const problem = Number.isFinite(amount) && !valid ? `Enter an amount between 1 and ${MAX_AMOUNT.toLocaleString("en-GB")}.` : null;

  return (
    <div className="flex w-full flex-col gap-2" role="group" aria-label="Choose a budget">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Budget levels">
        {LEVELS.map((level) => (
          <Button
            key={level.id}
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled}
            // An intent payload: the text "low budget" can also be read as a
            // low sustainability priority by the NLU.
            onClick={() => onSubmit(`/inform_budget{"budget": "${level.id}"}`, `${level.label} budget`)}
          >
            {level.label}
            <span className="font-normal text-muted-foreground">· {level.hint}</span>
          </Button>
        ))}
      </div>

      <form
        className="flex w-full max-w-md flex-col gap-2 rounded-lg border bg-card p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) onSubmit(`${amount} ${currency}`, `${formatMoney(amount, currency)} in total`);
        }}
      >
        <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Wallet className="size-3.5" aria-hidden="true" />
          Or give a total for the whole trip
        </p>
        <div className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label htmlFor={`${ids}-currency`} className="text-xs text-muted-foreground">Currency</label>
            <select
              id={`${ids}-currency`}
              value={currency}
              onChange={(e) => setCurrency(e.target.value as Currency)}
              className="h-8 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {CURRENCIES.map((code) => <option key={code} value={code}>{code}</option>)}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={`${ids}-amount`} className="text-xs text-muted-foreground">Total amount</label>
            <input
              id={`${ids}-amount`}
              type="number"
              inputMode="numeric"
              min={1}
              max={MAX_AMOUNT}
              step="any"
              placeholder="e.g. 1200"
              value={Number.isFinite(amount) ? amount : ""}
              onChange={(e) => setAmount(e.target.valueAsNumber)}
              className="h-8 w-32 rounded-md border border-input bg-transparent px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <Button type="submit" size="sm" disabled={disabled || !valid}>
            Use this budget
          </Button>
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Common amounts">
          {QUICK_AMOUNTS.map((n) => (
            <Button key={n} type="button" size="xs" variant={amount === n ? "default" : "outline"} aria-pressed={amount === n} onClick={() => setAmount(n)}>
              {formatMoney(n, currency)}
            </Button>
          ))}
        </div>
        <p className={`text-sm ${problem ? "text-red-700 dark:text-red-400" : "font-medium"}`} role="status" aria-live="polite">
          {problem ?? (valid ? `${formatMoney(amount, currency)} for the whole trip` : "")}
        </p>
      </form>
    </div>
  );
}
