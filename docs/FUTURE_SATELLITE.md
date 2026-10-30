# Future: satellite harvest sensing

**Status: future (v0.7), not built.** There is no satellite code in Vaari, nothing imports a satellite library, and `GET /api/health` reports `satellite: "disabled"`. This page records the design so that, when the work is picked up, it starts from the right problem and the right limits.

## 1. The problem

Every season some requests arrive with **no harvest date**. The farmer does not know it yet, or the operator did not write it down. Vaari puts these in `needs_info`: the scheduler cannot plan them, because the deadline (`sow_by = harvest_date + 20 days`) depends on the harvest date. In the seed, 5 of 40 requests are like this. Today someone has to phone each farmer.

Satellite images could suggest a likely harvest window for a registered plot ("harvested between 18 and 24 October") so the operator can ask a sharper question, or plan provisionally. That is all. It is a hint for a person, not a date the scheduler trusts.

## 2. The rule that does not bend

**The sensor may suggest; it never overrides a human.**

- A date the farmer or operator states always wins, even if the sensor disagrees.
- A suggestion is shown as an interval with its evidence ("cleared between the 18 Oct and 24 Oct images"), never as a single day, and always badged (for example `harvest window from satellite`).
- A suggestion never moves a request out of `needs_info` by itself. A person accepts it (it then becomes their stated date) or ignores it.
- It never feeds anything that could count against a farmer: no penalties, no flags on records, nothing in the evidence checks.
- When the sensor is down, slow or unsure, the screen says so and the loop carries on exactly as today.

## 3. Interface sketch

Same pattern as the register reader: one interface, a mock first, the real thing behind configuration, and nothing in the core importing it.

```python
from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class HarvestWindow:
    plot_id: int
    earliest: date | None          # last image that still showed standing crop, plus one day
    latest: date | None            # first image that showed a cleared or stubble field
    state: str                     # "harvested" | "standing" | "unknown"
    basis: list[str]               # e.g. ["S2 2026-10-17 standing", "S1 2026-10-23 cleared"]
    clear_looks: int               # usable observations in the period checked
    confidence: str                # "high" | "low" | "none", from clear_looks and agreement, never a fake probability
    source: str                    # "mock" | "sentinel-2" | "sentinel-1" | "both" | "exported by hand"


class HarvestSensor(Protocol):
    def window(self, plot_id: int, geometry_geojson: str, season_start: date, today: date) -> HarvestWindow: ...

# MockHarvestSensor            fixed answers for tests and demos
# Sentinel2HarvestSensor       optical, cloud-masked
# Sentinel1HarvestSensor       radar, works through cloud and smoke
# CombinedHarvestSensor        both, reporting where they disagree
```

Where it would plug in: a background job fills an `orbit_check` table (designed in `docs/ARCHITECTURE.md`, never created by the core) for plots of `needs_info` requests. The Desk shows the window beside the request with an "Use this as the harvest date?" button. `/api/health` changes `satellite` from `disabled` to `ok`, `stale` or `down`.

## 4. Candidate data

| Source | What it sees | Resolution | How often | Strengths | Weaknesses |
| --- | --- | --- | --- | --- | --- |
| **Sentinel-2** (optical, Copernicus, free) | Red, near-infrared and shortwave-infrared reflectance. Standing paddy is green (high NDVI); a harvested or burnt field drops sharply | 10 m (red, NIR), 20 m (SWIR) | Every 5 days with two satellites | Clear signal on a clear day; burnt and harvested fields look different in SWIR | Blind under cloud, thick haze and smoke |
| **Sentinel-1** (C-band radar, Copernicus, free) | Backscatter (VV, VH). Harvest changes the field's structure and the VH/VV ratio | About 10 m after processing; speckle needs averaging over the plot | 6-day repeat with two satellites; how often Punjab is actually imaged depends on the acquisition plan | Sees through cloud and smoke, day or night | Noisier; soil moisture and residue confuse it; needs careful calibration per region |

Current state, to check again before building:

- **Sentinel-2.** Two satellites in the same orbit, 180° apart, give a 5-day revisit (ESA). Sentinel-2C took over from Sentinel-2A on 21 January 2025. Sentinel-2A was then given a temporary, one-year extended campaign from March 2025, as a third unit adding observations. Whether that third unit is still flying when this is built must be checked.
- **Sentinel-1.** Sentinel-1B failed in 2021, leaving one satellite. Sentinel-1C (launched December 2024) and Sentinel-1D (launched 4 November 2025) restored the pair. The nominal 6-day repeat cycle was re-established on 24 June 2026, and Sentinel-1A's operations ended in June 2026. Many land areas have in the past been imaged on a 12-day cycle even with two satellites, so the real number of Punjab acquisitions per season must be counted, not assumed.

## 5. Cloud cover, haze and revisit limits

The paddy harvest in Punjab, and the burning that follows it, peaks from the second half of October to the first half of November (Kumar et al., 2019, from VIIRS fire counts and satellite harvest estimates). The monsoon has usually withdrawn by then, so optical images are more often clear than in the growing season. But:

- **Smoke and haze** from residue burning, and fog later in November, can spoil exactly the images that matter.
- With a 5-day optical revisit and some images lost, the gap between two usable looks at one plot can easily be 10 to 15 days. The window "harvested between A and B" can then be wider than the 20-day sowing window it is meant to help with. A window wider than about 10 days is not worth showing.
- Small plots (1 to 2 acres is common) are only a few dozen 10 m pixels. Edge pixels mix with roads, bunds and neighbouring fields, so use an inward buffer of at least one pixel and require a minimum number of clean pixels.
- Radar fills gaps but needs its own validation; it does not inherit the optical method's accuracy.

So the sensor must be allowed to say "unknown", and that must be a normal, common answer.

## 6. Validation plan on Punjab paddy

Nothing is shown to an operator until this has been done and published as counts (*k of N*), as with the register reader.

1. **Ground truth.** Over one season, collect true harvest dates for at least 150 plots across at least 3 districts, with consent: from completed Vaari jobs (the Done time is a date the machine was in the field after harvest), operator calls, and field visits. Record plot boundaries (from the plot GeoJSON) and plot size.
2. **Freeze the method and the bar before looking at the results.** For example: in at least 120 of 150 plots, the true harvest date falls inside the reported window; median window width at most 7 days; and on plots where the sensor says "harvested", fewer than 5 of 150 are actually still standing (a false "harvested" is the costly error, because it pulls a deadline forward).
3. **Hold out a district.** Tune on two districts, report on the third, so the numbers are not flattered by local fitting.
4. **Report by condition:** plot size bands, optical-only vs radar-only vs both, and smoky vs clear weeks. Report "unknown" rates as plainly as accuracy.
5. **Compare with doing nothing:** how many `needs_info` requests would the suggestions have helped, measured against how operators handle them today (a phone call).
6. **Decide.** If the bar is not met, the feature stays off. A sensor that is often silent but right when it speaks is acceptable. One that is often confidently wrong is not.

## 7. What it will never do

- Override a stated harvest date, or change a request's status by itself.
- Accuse, penalise or flag a farmer (no burning detection tied to a person through Vaari).
- Hide that it is a guess: every suggestion carries its window, its basis and its badge.
- Block the core loop: if it is down, slow, or switched off, everything works as it does today.

## Sources

- ESA, Sentinel-2 facts and figures (5-day revisit with two satellites): https://www.esa.int/Our_Activities/Observing_the_Earth/Copernicus/Sentinel-2/Facts_and_figures
- Copernicus, transfer of duty from Sentinel-2A to Sentinel-2C on 21 January 2025: https://sentinels.copernicus.eu/-/precise-timing-of-transfer-of-duty-from-sentinel-2a-to-sentinel-2c-on-21-january
- Copernicus Data Space Ecosystem, Sentinel-2A extended campaign from 13 March 2025: https://dataspace.copernicus.eu/news/2025-2-28-sentinel-2a-extended-campaign-starting-march-13-2025
- Copernicus Data Space Ecosystem, Sentinel-1C/D final orbital configuration (6-day repeat from 24 June 2026): https://dataspace.copernicus.eu/node/4010
- Copernicus Data Space Ecosystem, Sentinel-1 orbital reconfiguration dates (Sentinel-1A operations ended 29 June 2026): https://dataspace.copernicus.eu/node/3949
- ASF, Sentinel-1 mission notes (12-day repeat per satellite; many land areas imaged every 12 days): https://hyp3-docs.asf.alaska.edu/sentinel1/
- Kumar, P. et al. (2019), Monitoring of rice crop in Punjab and Haryana with respect to residue burning, ISPRS Archives XLII-3/W6: https://isprs-archives.copernicus.org/articles/XLII-3-W6/31/2019/
- Detecting growth of paddy in Punjab using SAR Sentinel-1 and Sentinel-2 data (2023), on cloud cover in the growing season and radar phenology: https://aminer.org/pub/646630f7d68f896efaaa5d17/detecting-growth-of-paddy-in-punjab-using-sar-sentinel-and-sentinel-data
