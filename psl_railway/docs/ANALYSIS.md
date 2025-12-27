# Seasons CSV Files Analysis

## Overview

The `data/seasons/` directory contains 9 CSV files with complete PSL match data including venues for seasons 2015-2016 through 2023-2024.

## File Structure

### Files
- `2015-2016.csv` - 281 matches
- `2016-2017.csv` - 286 matches
- `2017-2018.csv` - 282 matches
- `2018-2019.csv` - 240 matches
- `2019-2020.csv` - 240 matches
- `2020-2021.csv` - 240 matches
- `2021-2022.csv` - 240 matches
- `2022-2023.csv` - 240 matches
- `2023-2024.csv` - 240 matches

**Total: 2,289 match records**

## Column Structure

### Common Columns (All Files)
- `Date` - Match date (YYYY-MM-DD format)
- `Time` - Match time (HH:MM format)
- `Home` - Home team name
- `Score` - Match score (format: "X–Y" using en dash)
- `Away` - Away team name
- `Attendance` - Attendance number (may be null)
- `Venue` - Match venue name (complete data)
- `Referee` - Referee name (may be null)
- `Match Report` - Link to match report

### Additional Columns (Older Files: 2015-2018)
- `Wk` - Week number
- `Day` - Day of week abbreviation
- `Notes` - Additional notes (usually null)
- `Unnamed: 0` - Index column

## Key Differences from `psl_final.csv`

| Feature | `psl_final.csv` | `seasons/*.csv` |
|---------|----------------|----------------|
| Venue | ❌ Missing | ✅ Complete |
| Score Format | Hyphen (-) | En dash (–) |
| Structure | Simple (5 cols) | Detailed (10-13 cols) |
| Date Range | Single file | Per-season files |
| Time | ❌ Missing | ✅ Included |
| Attendance | ❌ Missing | ✅ Included |
| Referee | ❌ Missing | ✅ Included |

## Data Quality

### Venue Data
- ✅ **100% coverage** - All files include Venue column
- ⚠️ **Older seasons (2015-2017)** - Some null values (14-16%)
- ✅ **Recent seasons (2018-2024)** - Complete venue data (0% nulls)
- ✅ **Consistent naming** - Venue names are standardized
- ✅ **44 unique venues** across all seasons

### Score Format
- Uses **en dash (–)** character, not hyphen (-)
- Format: "X–Y" (e.g., "2–1", "0–0")
- Requires parsing to extract home_goals and away_goals

### Date Format
- Consistent YYYY-MM-DD format across all files
- Dates are properly formatted and parseable

## Sample Data

```
Date,Time,Home,Score,Away,Attendance,Venue,Referee,Match Report
2023-08-04,19:30,Sekhukhune United FC,1–2,Sundowns,,Peter Mokaba Stadium,Sikhumbuzo Gasa,Match Report
2023-08-05,15:00,Golden Arrows,1–1,Moroka Swallows,,Mpumalanga Town Stadium,Tshidiso Maruping,Match Report
```

## Recommended Usage

### For Database Import

1. **Use seasons files instead of `psl_final.csv`** for complete historical data
2. **Parse score format** - Handle en dash (–) character
3. **Extract goals** - Split score on en dash to get home_goals and away_goals
4. **Map columns**:
   - `Date` → `date`
   - `Home` → `home_team`
   - `Away` → `away_team`
   - `Score` → parse to `home_goals` and `away_goals`
   - `Venue` → `venue`

### Advantages

- ✅ Complete venue information
- ✅ More detailed match data
- ✅ Organized by season
- ✅ Includes additional metadata (time, attendance, referee)

## Key Statistics

- **Total matches**: 2,289 records
- **Unique venues**: 44 different stadiums
- **Unique teams**: 29 different teams
- **Venue coverage**: 
  - 2015-2017: ~85% (some nulls)
  - 2018-2024: 100% (complete)

## Integration Recommendations

1. **Update `db/import_csv.py`** to handle seasons files
2. **Create new import function** `import_seasons_data()` that:
   - Processes all season files
   - Handles en dash score format (parse "X–Y" to extract goals)
   - Maps columns correctly:
     - `Date` → `date`
     - `Home` → `home_team`
     - `Away` → `away_team`
     - `Score` → parse to `home_goals` and `away_goals`
     - `Venue` → `venue`
   - Handles null venues gracefully (use empty string)
   - Merges with existing matches table
   - Prevents duplicates using UNIQUE constraint
3. **Consider replacing** `psl_final.csv` import with seasons import for better data quality (includes venues)
4. **Score parsing**: Use regex or string split on en dash character (–) to extract goals

