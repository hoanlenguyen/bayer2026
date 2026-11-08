import type { GuidedExample } from "../api/types";

/** The Ask start screen's example questions, in order. A click sends the text exactly as if it were typed (ordinary Ask).
 *  Kept in the bundle so the start screen needs no request. Texts mirror backend/app/guided_examples.py,
 *  which test_guided_examples.py checks. */
export const GUIDED_EXAMPLES: readonly GuidedExample[] = [
  { id: "nubeqa-sales-shipments", placement: "visible",
    text: "Build a monthly dashboard comparing Nubeqa net sales and units shipped by market in France and Germany." },
  { id: "lynkuet-stock-delivery", placement: "visible",
    text: "Build a monthly dashboard comparing Lynkuet inventory coverage and OTIF by market in France and Germany." },
  { id: "kerendia-access-shipments", placement: "more",
    text: "Build a monthly dashboard comparing Kerendia market access coverage and units shipped by market in Italy and Spain." },
  { id: "eylea-sales-delivery", placement: "more",
    text: "Build a monthly dashboard comparing Eylea net sales and OTIF by market in Canada and the United States." },
  { id: "xarelto-stock-shipments", placement: "more",
    text: "Build a monthly dashboard comparing Xarelto inventory coverage and units shipped by market in Brazil and Mexico." },
];
