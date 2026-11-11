"""Phase 4 — exploratory & statistical analysis of BAAC 2019–2025 (metropolitan France).

Read-only on the analytics layer (analytics.accident_fact, analytics.road_user_fact). Outputs:
  reports/phase4/tables/*.csv   aggregated results and test statistics
  reports/phase4/figures/*.png  5 figures
Tests: Pearson chi-square of independence (scipy) + Cramér's V. With N in the hundreds of thousands every
association is "significant"; effect sizes (V) and proportions with 95 % Wilson intervals carry the message.
Descriptive / associational only — no causal claims, no models.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg
import seaborn as sns
from scipy.stats import chi2_contingency

from db_config import conninfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "phase4"
FIG, TAB = OUT / "figures", OUT / "tables"
FIG.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)

# English labels for ONISR codes (ONISR "Description des bases de données annuelles 2005-2025")
LABELS = {
    "lum": {1: "Daylight", 2: "Dusk / dawn", 3: "Night, no street lighting", 4: "Night, lighting off", 5: "Night, lighting on"},
    "atm": {1: "Normal", 2: "Light rain", 3: "Heavy rain", 4: "Snow / hail", 5: "Fog / smoke", 6: "Strong wind / storm",
            7: "Dazzling", 8: "Overcast", 9: "Other"},
    "surf": {1: "Normal", 2: "Wet", 3: "Puddles", 4: "Flooded", 5: "Snow-covered", 6: "Mud", 7: "Icy", 8: "Oil / grease", 9: "Other"},
    "agg": {1: "Outside built-up area", 2: "Inside built-up area"},
    "catr_grp": {1: "Motorway", 2: "National road", 3: "Departmental road", 4: "Communal / metropolitan road",
                 5: "Off public network", 6: "Car park", 9: "Other"},
    "catu": {1: "Driver", 2: "Passenger", 3: "Pedestrian"},
    "sexe": {1: "Male", 2: "Female"},
    "grav": {1: "Unhurt", 4: "Light", 3: "Hospitalised", 2: "Killed"},
}
WEEKDAYS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}
SEV_ORDER = ["light", "hospitalised", "fatal"]
sns.set_theme(style="whitegrid", context="notebook")
C_MAIN, C_ALT, C_COVID = "#2b6cb0", "#c05621", "#9b2c2c"


def wilson(k, n, z=1.96):
    k, n = np.asarray(k, float), np.asarray(n, float)
    p = k / n
    d = 1 + z ** 2 / n
    c = (p + z ** 2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / d
    return p, c - h, c + h


def chi2_v(table: pd.DataFrame) -> dict:
    t = table.loc[table.sum(axis=1) > 0, table.sum(axis=0) > 0]
    chi2, p, dof, exp = chi2_contingency(t.values)
    n = t.values.sum()
    v = np.sqrt(chi2 / (n * (min(t.shape) - 1)))
    return {"n": int(n), "chi2": round(chi2, 1), "dof": dof, "p_value": p, "cramers_v": round(v, 3),
            "min_expected": round(exp.min(), 1)}


def main() -> int:
    with psycopg.connect(**conninfo()) as conn:
        conn.read_only = True                          # analysis never writes to the database

        def query(sql):
            cur = conn.execute(sql)
            return pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])

        year = query("""select year, count(*) accidents, count(*) filter (where accident_severity='fatal') fatal_accidents,
                        sum(n_killed) killed, sum(n_hospitalised) hospitalised, sum(n_light) light, sum(n_unhurt) unhurt,
                        sum(n_grav_unknown) grav_unknown, sum(n_users) users, sum(n_users_excl_fugitive) users_excl_fugitive
                        from analytics.accident_fact group by 1 order by 1""").astype(int)
        month = query("select year, month, count(*) n from analytics.accident_fact group by 1, 2").astype(int)
        wdh = query("""select year, weekday, hour, count(*) n, count(*) filter (where accident_severity='fatal') fatal
                       from analytics.accident_fact group by 1, 2, 3""").astype(int)
        env = {}
        for f, expr in (("lum", "lum"), ("atm", "atm"), ("surf", "surf"), ("agg", "agg"),
                        ("catr_grp", "case when catr = 7 then 4 else catr end")):          # CATR7_UNSTABLE: group 4 + 7
            env[f] = query(f"""select {expr} as value, accident_severity, count(*) n from analytics.accident_fact
                               group by 1, 2""")
        surf_conflict = int(query("select count(*) c from analytics.accident_fact where surf_conflict")["c"][0])
        users = query("""select catu, sexe, age_group, grav,
                         case when catu = 3 then 'Pedestrian' when catv = 1 then 'Bicycle' when catv = 80 then 'E-bike'
                              when catv in (50, 60) then 'Personal mobility device'
                              when catv in (2,30,31,32,33,34,41,42,43) then 'Powered 2/3-wheeler'
                              when catv = 7 then 'Car' when catv = 10 then 'Light commercial'
                              when catv between 13 and 17 then 'Heavy goods' when catv in (37, 38) then 'Bus / coach'
                              else 'Other / unknown' end as mode,
                         is_fugitive_like, count(*) n
                         from analytics.road_user_fact group by 1, 2, 3, 4, 5, 6""")
        db = query("""select (select count(*) from analytics.accident_fact) acc,
                             (select sum(n_killed) from analytics.accident_fact) killed,
                             (select count(*) from clean.road_user u join clean.accident a using (num_acc) where a.is_metro and u.grav = 2) killed_clean,
                             (select count(*) from analytics.road_user_fact) users,
                             (select sum(n_accidents) from analytics.agg_year_department) acc_dep""").iloc[0]

    results = {}
    # ------------------------------------------------------------ 1. overview
    y = year.copy()
    y["killed_per_100_accidents"] = (100 * y.killed / y.accidents).round(2)
    y["fatal_accident_share_pct"] = (100 * y.fatal_accidents / y.accidents).round(2)
    y["hospitalised_per_100_accidents"] = (100 * y.hospitalised / y.accidents).round(1)
    y.to_csv(TAB / "01_annual_overview.csv", index=False)
    ref = y[y.year != 2020][["accidents", "killed", "hospitalised", "light"]].mean()
    cov = y[y.year == 2020].iloc[0]
    covid = {k: round(100 * (cov[k] / ref[k] - 1), 1) for k in ("accidents", "killed", "hospitalised", "light")}
    results["covid_2020_vs_other_years_mean_pct"] = covid
    sev = env["agg"].groupby("accident_severity").n.sum().reindex(SEV_ORDER)
    results["severity_distribution_pct"] = (100 * sev / sev.sum()).round(2).to_dict()
    yy = y[y.year != 2020]
    results["fatal_share_trend_excl_2020"] = chi2_v(pd.DataFrame({"fatal": yy.fatal_accidents, "non_fatal": yy.accidents - yy.fatal_accidents}).set_index(yy.year))

    # ------------------------------------------------------------ 2. temporal
    m = month.pivot(index="month", columns="year", values="n")
    m.to_csv(TAB / "02_monthly_accidents.csv")
    april = month[(month.month == 4)].set_index("year").n
    results["april_2020_vs_other_years_mean_pct"] = round(100 * (april[2020] / april.drop(2020).mean() - 1), 1)
    w = wdh[wdh.year != 2020]
    heat = (w.groupby(["weekday", "hour"]).n.sum() / 6).unstack("hour").rename(index=WEEKDAYS)     # mean per year, 6 years
    heat.round(1).to_csv(TAB / "03_weekday_hour_mean_per_year_excl2020.csv")
    hour = wdh.groupby("hour")[["n", "fatal"]].sum()
    p, lo, hi = wilson(hour.fatal, hour.n)
    hour = hour.assign(fatal_share=p, ci_low=lo, ci_high=hi)
    hour.to_csv(TAB / "04_fatal_share_by_hour.csv")
    tod = wdh.assign(night=lambda d: np.where(d.hour < 6, "00-05", "06-23")).groupby("night")[["n", "fatal"]].sum()
    results["fatal_share_night_vs_day_pct"] = (100 * tod.fatal / tod.n).round(2).to_dict()
    results["night_vs_day_test"] = chi2_v(pd.DataFrame({"fatal": tod.fatal, "non_fatal": tod.n - tod.fatal}))
    wk = wdh.assign(weekend=lambda d: d.weekday >= 6).groupby("weekend")[["n", "fatal"]].sum()
    results["fatal_share_weekend_vs_weekday_pct"] = {("weekend" if k else "weekday"): round(100 * v.fatal / v.n, 2) for k, v in wk.iterrows()}
    results["weekend_test"] = chi2_v(pd.DataFrame({"fatal": wk.fatal, "non_fatal": wk.n - wk.fatal}))

    # ------------------------------------------------------------ 3. environmental factors (accident level)
    env_rows, env_tests = [], []
    for f, d in env.items():
        missing = int(d[d.value.isna()].n.sum())
        d = d.dropna(subset=["value"]).astype({"value": int})
        t = d.pivot_table(index="value", columns="accident_severity", values="n", aggfunc="sum", fill_value=0).reindex(columns=SEV_ORDER, fill_value=0)
        tot = t.sum(axis=1)
        p, lo, hi = wilson(t["fatal"], tot)
        for v in t.index:
            env_rows.append({"factor": f, "code": v, "label": LABELS[f].get(v, str(v)), "accidents": int(tot[v]),
                             "fatal_share": p[t.index.get_loc(v)], "ci_low": lo[t.index.get_loc(v)], "ci_high": hi[t.index.get_loc(v)],
                             "hospitalised_share": t.loc[v, "hospitalised"] / tot[v]})
        env_tests.append({"factor": f, "outcome": "accident severity (light/hospitalised/fatal)", "excluded_not_recorded": missing,
                          **chi2_v(t)})
    env_df = pd.DataFrame(env_rows)
    env_df.to_csv(TAB / "05_environment_severity.csv", index=False)
    env_tests = pd.DataFrame(env_tests)

    # ------------------------------------------------------------ 4. road users (user level)
    u = users.copy()
    n_users_all = int(u.n.sum())
    excl = {"fugitive_like": int(u[u.is_fugitive_like].n.sum()), "grav_unknown": int(u[~u.is_fugitive_like & u.grav.isna()].n.sum())}
    u = u[~u.is_fugitive_like & u.grav.notna()].astype({"grav": int})
    u["ksi"] = u.grav.isin([2, 3])                     # killed or seriously (hospitalised) injured
    user_tests, user_rows = [], []
    for f in ("catu", "sexe", "age_group", "mode"):
        d = u.dropna(subset=[f]) if f != "mode" else u
        missing = int(u.n.sum() - d.n.sum())
        t = d.pivot_table(index=f, columns="grav", values="n", aggfunc="sum", fill_value=0)[[1, 4, 3, 2]]
        t.columns = ["unhurt", "light", "hospitalised", "killed"]
        tot = t.sum(axis=1)
        pk, lk, hk = wilson(t.killed, tot)
        pksi, lksi, hksi = wilson(t.killed + t.hospitalised, tot)
        for i, v in enumerate(t.index):
            user_rows.append({"factor": f, "value": LABELS.get(f, {}).get(v, v) if f in ("catu", "sexe") else v, "users": int(tot[v]),
                              "killed_share": pk[i], "killed_ci_low": lk[i], "killed_ci_high": hk[i],
                              "ksi_share": pksi[i], "ksi_ci_low": lksi[i], "ksi_ci_high": hksi[i]})
        user_tests.append({"factor": f, "outcome": "user severity (unhurt/light/hospitalised/killed)", "excluded_not_recorded": missing, **chi2_v(t)})
    user_df = pd.DataFrame(user_rows)
    user_df.to_csv(TAB / "06_road_user_severity.csv", index=False)
    asx = u.dropna(subset=["age_group", "sexe"]).groupby(["age_group", "sexe"]).apply(
        lambda g: pd.Series({"users": g.n.sum(), "ksi": g.loc[g.ksi, "n"].sum()}), include_groups=False).reset_index()
    asx["ksi_share"], asx["ci_low"], asx["ci_high"] = wilson(asx.ksi, asx.users)
    asx.to_csv(TAB / "07_ksi_by_age_sex.csv", index=False)

    tests = pd.concat([env_tests, pd.DataFrame(user_tests),
                       pd.DataFrame([{"factor": "night (00-05) vs day", "outcome": "fatal accident", **results["night_vs_day_test"]},
                                     {"factor": "weekend vs weekday", "outcome": "fatal accident", **results["weekend_test"]},
                                     {"factor": "year (excl. 2020)", "outcome": "fatal accident", **results["fatal_share_trend_excl_2020"]}])],
                      ignore_index=True)
    tests["p_value"] = tests.p_value.map(lambda p: f"{p:.1e}")
    tests.to_csv(TAB / "08_statistical_tests.csv", index=False)

    # ------------------------------------------------------------ figures
    # F1 annual overview
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    colors = [C_COVID if yr == 2020 else C_MAIN for yr in y.year]
    for a, col, lab in ((ax, "accidents", "Injury accidents"), (ax2, "killed", "Persons killed (≤ 30 days)")):
        a.bar(y.year, y[col], color=colors, alpha=.85)
        a.set_ylabel(lab); a.set_ylim(0, y[col].max() * 1.15)
        for yr, v in zip(y.year, y[col]):
            a.annotate(f"{v:,}".replace(",", " "), (yr, v), textcoords="offset points", xytext=(0, 3), ha="center", fontsize=8)
    ax.set_title("Injury accidents and fatalities, metropolitan France 2019–2025 (2020 in red: COVID-19 lockdowns)", fontsize=11)
    ax2.set_xticks(y.year)
    fig.tight_layout(); fig.savefig(FIG / "fig1_annual_overview.png", dpi=150); plt.close(fig)

    # F2 monthly profile: 2020 vs other years
    fig, ax = plt.subplots(figsize=(9, 4.5))
    other = m.drop(columns=2020)
    ax.fill_between(m.index, other.min(axis=1), other.max(axis=1), color=C_MAIN, alpha=.15, label="2019, 2021–2025 (range)")
    ax.plot(m.index, other.mean(axis=1), color=C_MAIN, lw=2, label="2019, 2021–2025 (mean)")
    ax.plot(m.index, m[2020], color=C_COVID, lw=2, marker="o", label="2020")
    ax.set_xticks(range(1, 13), ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])
    ax.set_ylabel("Injury accidents per month"); ax.legend(frameon=False)
    ax.set_title("Monthly accidents: the 2020 lockdown anomaly (April 2020: {:+.0f} %)".format(results["april_2020_vs_other_years_mean_pct"]), fontsize=11)
    fig.tight_layout(); fig.savefig(FIG / "fig2_monthly_covid.png", dpi=150); plt.close(fig)

    # F3 weekday x hour heatmap + fatal share by hour
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 7), gridspec_kw={"height_ratios": [1.4, 1]}, sharex=False)
    sns.heatmap(heat, ax=a1, cmap="Blues", cbar_kws={"label": "accidents / year"}, linewidths=.2)
    a1.set_xlabel(""); a1.set_ylabel(""); a1.set_title("Mean accidents per year by weekday and hour (2019, 2021–2025)", fontsize=11)
    a2.fill_between(hour.index, 100 * hour.ci_low, 100 * hour.ci_high, color=C_ALT, alpha=.25)
    a2.plot(hour.index, 100 * hour.fatal_share, color=C_ALT, marker="o", lw=2)
    a2.set_xticks(range(0, 24)); a2.set_xlabel("Hour of day"); a2.set_ylabel("Fatal accidents (%)")
    a2.set_title("Share of accidents that are fatal, by hour (95 % CI, 2019–2025)", fontsize=11)
    fig.tight_layout(); fig.savefig(FIG / "fig3_weekday_hour.png", dpi=150); plt.close(fig)

    # F4 environmental factors: fatal share with CI
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.5))
    for ax, f, title in zip(axes.ravel(), ("lum", "agg", "atm", "surf"), ("Lighting", "Location", "Weather", "Road surface")):
        d = env_df[(env_df.factor == f) & (env_df.accidents >= 200)].sort_values("fatal_share")
        ax.errorbar(100 * d.fatal_share, d.label, xerr=[100 * (d.fatal_share - d.ci_low), 100 * (d.ci_high - d.fatal_share)],
                    fmt="o", color=C_MAIN, ecolor="#999", capsize=3)
        v = env_tests.set_index("factor").loc[f, "cramers_v"]
        ax.set_title(f"{title} (Cramér's V = {v})", fontsize=10); ax.set_xlabel("Fatal accidents (%)")
    fig.suptitle("Share of accidents that are fatal by environmental condition, 2019–2025 (categories ≥ 200 accidents, 95 % CI)", fontsize=11)
    fig.tight_layout(); fig.savefig(FIG / "fig4_environment_fatal_share.png", dpi=150); plt.close(fig)

    # F5 road users: KSI share by age x sex, and killed share by mode
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5))
    for sx, col in ((1, C_MAIN), (2, C_ALT)):
        d = asx[asx.sexe == sx].sort_values("age_group")
        a1.errorbar(d.age_group, 100 * d.ksi_share, yerr=[100 * (d.ksi_share - d.ci_low), 100 * (d.ci_high - d.ksi_share)],
                    fmt="o-", color=col, capsize=3, label=LABELS["sexe"][sx])
    a1.set_ylabel("Killed or hospitalised (%)"); a1.set_xlabel("Age group"); a1.legend(frameon=False)
    a1.set_title("Users killed or hospitalised, by age and sex", fontsize=11); a1.tick_params(axis="x", rotation=45)
    d = user_df[user_df.factor == "mode"].sort_values("killed_share")
    a2.barh(d.value, 100 * d.killed_share, color=C_MAIN, xerr=[100 * (d.killed_share - d.killed_ci_low), 100 * (d.killed_ci_high - d.killed_share)])
    a2.set_xlabel("Killed (%)"); a2.set_title("Users killed, by travel mode", fontsize=11)
    fig.suptitle("Outcome of road users involved in injury accidents, 2019–2025 (fugitive-like and unknown severity excluded)", fontsize=11)
    fig.tight_layout(); fig.savefig(FIG / "fig5_road_users.png", dpi=150); plt.close(fig)

    # ------------------------------------------------------------ reconciliation with the database
    recon = {
        "accidents: annual table = accident_fact = department aggregate": (int(y.accidents.sum()), int(db.acc), int(db.acc_dep)),
        "killed: annual table = accident_fact = clean.road_user": (int(y.killed.sum()), int(db.killed), int(db.killed_clean)),
        "accidents: monthly table": (int(m.values.sum()), int(db.acc)),
        "accidents: weekday x hour table": (int(wdh.n.sum()), int(db.acc)),
        "accidents: each environmental table": tuple(int(d.n.sum()) for d in env.values()) + (int(db.acc),),
        "users: road-user table = road_user_fact": (n_users_all, int(db.users)),
    }
    ok = all(len(set(v)) == 1 for v in recon.values())
    pd.DataFrame([{"check": k, "values": v, "status": "pass" if len(set(v)) == 1 else "FAIL"} for k, v in recon.items()]).to_csv(
        TAB / "00_reconciliation.csv", index=False)

    # ------------------------------------------------------------ console summary (used for the report)
    pd.set_option("display.width", 220, "display.max_columns", 30)
    print("RECONCILIATION:", "PASS" if ok else "FAIL")
    for k, v in recon.items():
        print(f"  {k}: {v}")
    print("\nANNUAL\n", y.to_string(index=False))
    print("\nRESULTS", {k: v for k, v in results.items() if not k.endswith("test") and "trend" not in k})
    print("\nTESTS\n", tests.to_string(index=False))
    print("\nusers excluded:", excl, "| surf conflicts (NULL):", surf_conflict)
    print("\nENV (fatal share %)\n", env_df.assign(fatal_pct=lambda d: (100 * d.fatal_share).round(2))[["factor", "label", "accidents", "fatal_pct"]].to_string(index=False))
    print("\nUSERS\n", user_df.assign(killed_pct=lambda d: (100 * d.killed_share).round(2), ksi_pct=lambda d: (100 * d.ksi_share).round(1))[["factor", "value", "users", "killed_pct", "ksi_pct"]].to_string(index=False))
    print("\nAGE x SEX KSI %\n", asx.assign(k=lambda d: (100 * d.ksi_share).round(1)).pivot(index="age_group", columns="sexe", values="k").to_string())
    print("\nfatal share by hour %:", (100 * hour.fatal_share).round(1).to_dict())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
