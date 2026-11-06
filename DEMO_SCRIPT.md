# Hackathon demo script (about 4 minutes)

**Before:** `python3 app.py`, open `http://localhost:5000`, go to **Guided demo**, click **Reset demo data**.
The street map needs internet; the app falls back to its built-in map if the venue wifi fails.

**Opening line (10 s):** "Every city app tells you *what* is broken. NammaFixtory tells you *what keeps breaking*."

| # | Click | Say | What the judges see |
|---|---|---|---|
| 1 | Step 1 | "Citizen A reports a pothole with a photo." | Reference number, photo read as pothole, priority with reasons |
| 2 | Step 2 | "Citizen B reports the same pothole in different words." | Duplicate suggested, two reports linked, counted once |
| 3 | Step 3 | "An officer records the repair and uploads an after photo." | Before/after comparison: "looks repaired, officer to confirm" |
| 4 | Step 4 | "The AI only recommends. A person confirms." | Officer confirmation, history timeline |
| 5 | Step 5 | "Weeks later the pothole is back." | **Recurrence detected**, flagged for inspection, possible causes to check |

Then open **Officer dashboard** (key `demo123`): open the flagged location, show the **history timeline**, the red ring
on **Map**, and **Download maintenance report**.

**Closing line (10 s):** "Fix today, prevent tomorrow: don't just close the complaint, find out why it keeps coming back."

## Questions to expect
* *Is the AI accurate?* "This prototype uses a baseline detector and synthetic photos. We report real accuracy only after testing on local data; the YOLO training path is built (`scripts/train_yolo.py`)."
* *Does it connect to GCC / CPGRAMS?* "Not yet. That needs permission. We designed it to complement existing channels."
* *Why not just use the existing grievance portals?* "They manage tickets. We keep the history of the road, which shows repeat failure."
* *Privacy?* "Contact details only with consent, never public; AI never decides alone; officer actions are logged."

The photos in the demo are synthetic illustrations and the data is sample data. Say so if asked.
