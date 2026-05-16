import sys
import re
import math


def calc_elo(wins, losses, draws):
    total = wins + losses + draws
    if total == 0:
        return None
    p = (wins + 0.5 * draws) / total
    if p == 0:
        elo_diff = float("-inf")
    elif p == 1:
        elo_diff = float("inf")
    else:
        elo_diff = -400 * math.log10(1 / p - 1)
    return total, p, elo_diff


def calc_ci_wilson(total, wins, draws, confidence=0.95):
    if total == 0:
        return None, None
    z = 1.96 if confidence == 0.95 else 2.576
    p_hat = (wins + 0.5 * draws) / total
    denominator = 1 + z**2 / total
    centre = (p_hat + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt((p_hat * (1 - p_hat) + z **
                           2 / (4 * total)) / total) / denominator
    p_low = max(0, centre - margin)
    p_high = min(1, centre + margin)

    def p_to_elo(p):
        if p <= 0.0001:
            return -800
        if p >= 0.9999:
            return 800
        return -400 * math.log10(1 / p - 1)
    elo_low = p_to_elo(p_low)
    elo_high = p_to_elo(p_high)
    return elo_low, elo_high


def format_result(wins, losses, draws):
    result = calc_elo(wins, losses, draws)
    if result is None:
        print("Error: no games played.")
        return
    total, p, elo_diff = result

    ci_low, ci_high = calc_ci_wilson(total, wins, losses)

    print(f"Total games: {total}")
    print(f"Wins: {wins}  Losses: {losses}  Draws: {draws}")
    print(f"Win rate: {p:.4f} ({p*100:.2f}%)")
    if math.isinf(elo_diff):
        if elo_diff > 0:
            print("Elo difference: +Inf (opponent too weak)")
        else:
            print("Elo difference: -Inf (opponent too strong)")
    else:
        print(f"Elo difference: {elo_diff:+.2f}")
    if ci_low is not None and ci_high is not None:
        print(f"95% CI: [{ci_low:+.2f}, {ci_high:+.2f}]")
    else:
        print("95% CI: cannot compute")

    if p > 0.95 or p < 0.05:
        print("Note: Extreme win rate. Elo estimate is unreliable.")
        print("      Find an opponent with closer strength for accurate rating.")
    elif total < 30:
        print("Note: sample size is very small (< 30 games). Results are NOT reliable.")
    elif total < 100:
        print("Note: sample size is small (< 100 games). Results may not be reliable.")
    elif total < 500:
        print("Note: sample size is moderate. Consider more games for higher confidence.")
    else:
        print("Note: sample size is sufficient for reasonable confidence.")


def parse_cutechess_file(filepath):
    pattern = re.compile(
        r"Score of\s+(.+?)\s+vs\s+(.+?):\s+(\d+)\s*-\s*(\d+)\s*-\s*(\d+)")
    results = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = pattern.search(line)
                if m:
                    engine1 = m.group(1).strip()
                    engine2 = m.group(2).strip()
                    wins = int(m.group(3))
                    losses = int(m.group(4))
                    draws = int(m.group(5))
                    results.append((engine1, engine2, wins, losses, draws))
    except FileNotFoundError:
        print(f"Error: file '{filepath}' not found.")
        sys.exit(1)
    return results


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python elo_calc.py <wins> <losses> <draws>")
        print("  python elo_calc.py --file <cutechess_output_file>")
        sys.exit(1)

    if args[0] == "--file":
        if len(args) < 2:
            print("Error: --file requires a file path argument.")
            sys.exit(1)
        filepath = args[1]
        results = parse_cutechess_file(filepath)
        if not results:
            print("No score lines found in the file.")
            sys.exit(1)
        for engine1, engine2, wins, losses, draws in results:
            print(f"=== {engine1} vs {engine2} ===")
            format_result(wins, losses, draws)
            print()
    else:
        if len(args) < 3:
            print("Error: provide wins, losses, and draws as three numbers.")
            sys.exit(1)
        try:
            wins = int(args[0])
            losses = int(args[1])
            draws = int(args[2])
        except ValueError:
            print("Error: wins, losses, and draws must be integers.")
            sys.exit(1)
        if wins < 0 or losses < 0 or draws < 0:
            print("Error: wins, losses, and draws must be non-negative.")
            sys.exit(1)
        format_result(wins, losses, draws)


if __name__ == "__main__":
    main()
