// Centralised, locale-aware formatting helpers.
//
// Pure functions, no side effects, no module-level mutable state — easy to unit
// test. All wrap the platform Intl APIs and degrade gracefully on bad input
// (return an empty string rather than throwing) so a single bad value never
// blanks a whole view.

const DEFAULT_LOCALE = 'zh-TW';

/** Coerce a Date | number | ISO-string into a valid Date, or null. */
function toDate(value) {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (value == null || value === '') return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * Format a date.
 *
 * @param {Date|number|string} date
 * @param {object} [opts]
 * @param {string} [opts.locale='zh-TW']
 * @param {'gregorian'|'roc'} [opts.era='gregorian'] - 'roc' = 民國紀年
 * @param {object} [opts.dateStyle] - any Intl.DateTimeFormat options merged in
 *   (e.g. { year:'numeric', month:'2-digit', day:'2-digit' }). When omitted a
 *   sensible numeric YYYY/MM/DD-style default is used.
 * @returns {string} formatted date, or '' for invalid input.
 */
export function formatDate(date, opts = {}) {
  const d = toDate(date);
  if (!d) return '';
  const { locale = DEFAULT_LOCALE, era = 'gregorian', ...rest } = opts;

  // 民國 (ROC) era: year = Gregorian year - 1911. Rendered as "民國114年..."
  // We compute the ROC year ourselves rather than relying on the 'roc'
  // calendar (uneven runtime support) so output is deterministic.
  if (era === 'roc') {
    const rocYear = d.getFullYear() - 1911;
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const yearLabel = rocYear > 0 ? `民國${rocYear}年` : `民國前${1 - rocYear}年`;
    return `${yearLabel}${mm}月${dd}日`;
  }

  const dtfOpts = Object.keys(rest).length
    ? rest
    : { year: 'numeric', month: '2-digit', day: '2-digit' };
  try {
    return new Intl.DateTimeFormat(locale, dtfOpts).format(d);
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

/**
 * Format a number with locale grouping.
 * @param {number} n
 * @param {string} [locale='zh-TW']
 * @param {object} [intlOpts] - extra Intl.NumberFormat options.
 * @returns {string} formatted number, or '' for non-finite input.
 */
export function formatNumber(n, locale = DEFAULT_LOCALE, intlOpts = {}) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '';
  try {
    return new Intl.NumberFormat(locale, intlOpts).format(n);
  } catch {
    return String(n);
  }
}

/**
 * Format a currency amount.
 * @param {number} n
 * @param {object} [opts]
 * @param {string} [opts.currency='TWD']
 * @param {string} [opts.locale='zh-TW']
 * @param {object} [opts.intlOpts] - extra Intl.NumberFormat options.
 * @returns {string} formatted currency, or '' for non-finite input.
 */
export function formatCurrency(n, opts = {}) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '';
  const { currency = 'TWD', locale = DEFAULT_LOCALE, intlOpts = {} } = opts;
  try {
    return new Intl.NumberFormat(locale, { style: 'currency', currency, ...intlOpts }).format(n);
  } catch {
    return String(n);
  }
}
