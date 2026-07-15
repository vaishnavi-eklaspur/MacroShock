"""Independent, dependency-free verification of MacroShock's formulas.

Runs with ONLY the Python standard library (no numpy/scipy), so it can validate the maths
in any environment. It re-derives each quantity from first principles with hand-implemented
linear algebra and checks it against the formulas used by the analytics core
(docs/METHODOLOGY.md).

    python scripts/verify_math.py

Exit code 0 = all checks passed.
"""
from __future__ import annotations

import math

# --------------------------------------------------------------------- tiny linear algebra
def mat_vec(A, x):
    return [sum(A[i][j] * x[j] for j in range(len(x))) for i in range(len(A))]


def vec_dot(a, b):
    return sum(ai * bi for ai, bi in zip(a, b))


def transpose(A):
    return [[A[i][j] for i in range(len(A))] for j in range(len(A[0]))]


def mat_mat(A, B):
    Bt = transpose(B)
    return [[vec_dot(row, col) for col in Bt] for row in A]


def solve(A, b):
    """Solve A x = b via Gaussian elimination with partial pivoting."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-15:
            raise ValueError("singular matrix")
        M[col], M[piv] = M[piv], M[col]
        pivot = M[col][col]
        M[col] = [v / pivot for v in M[col]]
        for r in range(n):
            if r != col:
                factor = M[r][col]
                M[r] = [M[r][k] - factor * M[col][k] for k in range(n + 1)]
    return [M[i][n] for i in range(n)]


def inverse(A):
    n = len(A)
    cols = []
    for i in range(n):
        e = [1.0 if j == i else 0.0 for j in range(n)]
        cols.append(solve(A, e))
    # cols are columns of the inverse
    return [[cols[j][i] for j in range(n)] for i in range(n)]


# --------------------------------------------------------------------- normal-dist quantile
def norm_ppf(p):
    """Acklam's rational approximation to the standard-normal inverse CDF."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= phigh:
        q = p - 0.5
        r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


# --------------------------------------------------------------------- check harness
PASS, FAIL = 0, 0


def check(name, condition, detail=""):
    global PASS, FAIL
    mark = "PASS" if condition else "FAIL"
    if condition:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{mark}] {name}" + (f"  ({detail})" if detail else ""))


def approx(a, b, tol=1e-9):
    return abs(a - b) < tol


# --------------------------------------------------------------------- 1. portfolio vol
def verify_volatility():
    print("1. Portfolio volatility  sigma_p = sqrt(wᵀΣw)")
    cov = [[0.04, 0.01], [0.01, 0.09]]
    w = [0.6, 0.4]
    quad = vec_dot(w, mat_vec(cov, w))                 # wᵀΣw
    sigma = math.sqrt(quad)
    # hand value: 0.36*0.04 + 2*0.6*0.4*0.01 + 0.16*0.09 = 0.0144+0.0048+0.0144 = 0.0336
    check("quadratic form wᵀΣw", approx(quad, 0.0336), f"{quad:.6f}")
    check("sigma_p", approx(sigma, math.sqrt(0.0336)), f"{sigma:.6f}")


# --------------------------------------------------------------------- 2. VaR / CVaR
def verify_var():
    print("2. Parametric VaR / CVaR")
    sigma = 0.03
    z95 = norm_ppf(0.95)
    var = z95 * sigma
    check("z_0.95 ~ 1.6449", approx(z95, 1.6448536269514722, 1e-4), f"{z95:.6f}")
    check("VaR = z*sigma", approx(var, 1.6448536 * 0.03, 1e-6), f"{var:.6f}")
    # CVaR = sigma * phi(z)/(1-alpha)
    phi = math.exp(-0.5 * z95 * z95) / math.sqrt(2 * math.pi)
    cvar = sigma * phi / (1 - 0.95)
    check("CVaR > VaR", cvar > var, f"CVaR={cvar:.6f} VaR={var:.6f}")


# --------------------------------------------------------------------- 3. MCTR Euler identity
def verify_risk_decomposition():
    print("3. Risk decomposition  sum(CCTR) == sigma_p (Euler)")
    cov = [[0.040, 0.006, 0.002],
           [0.006, 0.090, 0.004],
           [0.002, 0.004, 0.160]]
    w = [0.5, 0.3, 0.2]
    sigma = math.sqrt(vec_dot(w, mat_vec(cov, w)))
    Sw = mat_vec(cov, w)
    marginal = [Sw[i] / sigma for i in range(3)]        # MCTR
    component = [w[i] * marginal[i] for i in range(3)]   # CCTR
    check("sum(CCTR) == sigma_p", approx(sum(component), sigma, 1e-12),
          f"sum={sum(component):.8f} sigma={sigma:.8f}")
    pct = [c / sigma for c in component]
    check("sum(PCTR) == 1", approx(sum(pct), 1.0, 1e-12), f"{sum(pct):.8f}")


# --------------------------------------------------------------------- 4. OLS betas
def verify_ols():
    print("4. OLS factor betas  beta = (XᵀX)⁻¹ Xᵀy")
    # Construct data with known betas and zero noise -> exact recovery.
    F = [[0.02, -0.01], [-0.015, 0.03], [0.01, 0.02], [0.04, -0.02],
         [-0.03, 0.01], [0.02, 0.025], [-0.01, -0.03], [0.05, 0.01]]
    true = [0.001, 0.8, -1.5]  # alpha, beta1, beta2
    X = [[1.0, f[0], f[1]] for f in F]
    y = [true[0] + true[1]*f[0] + true[2]*f[1] for f in F]
    Xt = transpose(X)
    XtX = mat_mat(Xt, X)
    Xty = mat_vec(Xt, y)
    beta = solve(XtX, Xty)
    check("alpha recovered", approx(beta[0], true[0], 1e-9), f"{beta[0]:.6f}")
    check("beta_1 recovered", approx(beta[1], true[1], 1e-9), f"{beta[1]:.6f}")
    check("beta_2 recovered", approx(beta[2], true[2], 1e-9), f"{beta[2]:.6f}")


# --------------------------------------------------------------------- 5. bond scenario pricing
def verify_bond_pricing():
    print("5. Scenario pricing  r = -D*dy + 0.5*C*dy^2")
    D, C, dy = 7.5, 75.0, -0.015
    r = -D * dy + 0.5 * C * dy * dy
    expected = 0.1125 + 0.5 * 75.0 * 0.000225   # 0.1125 + 0.0084375
    check("IEF return under -150bps", approx(r, expected, 1e-12), f"{r:.6f}")


# --------------------------------------------------------------------- 6. reverse stress
def verify_reverse_stress():
    print("6. Reverse stress  s* = -L·Σ_F g/(gᵀΣ_F g),  g = Bᵀw")
    B = [[1.0, 0.0], [0.0, -7.5], [0.5, -4.0]]
    Sigma = [[0.16**2/52, 0.0], [0.0, 0.010**2/52]]
    w = [0.5, 0.3, 0.2]
    Bt = transpose(B)
    g = mat_vec(Bt, w)                       # g = Bᵀ w  (length 2)
    Sg = mat_vec(Sigma, g)
    denom = vec_dot(g, Sg)
    L = 0.20
    s = [(-L) * Sg[k] / denom for k in range(2)]
    implied = vec_dot(g, s)                   # must equal -L
    check("gᵀs* == -L (hits target loss)", approx(implied, -L, 1e-12),
          f"implied={implied:.8f} target={-L}")
    # Minimum-norm: any feasible perturbation along null(g) cannot reduce Mahalanobis distance.
    inv = inverse(Sigma)
    d0 = vec_dot(s, mat_vec(inv, s))
    null_dir = [g[1], -g[0]]                  # g·null_dir = 0
    worse = True
    for eps in (-0.005, 0.005):
        s2 = [s[0] + eps*null_dir[0], s[1] + eps*null_dir[1]]
        if vec_dot(s2, mat_vec(inv, s2)) < d0 - 1e-15:
            worse = False
    check("s* is minimum-Mahalanobis (most plausible)", worse, f"d*={d0:.6e}")


def _cornish_fisher_quantile(z, S, K):
    return (z + (z**2 - 1) / 6 * S + (z**3 - 3 * z) / 24 * K - (2 * z**3 - 5 * z) / 36 * S**2)


def verify_cornish_fisher():
    print("7. Cornish-Fisher VaR quantile adjustment")
    z95 = norm_ppf(0.05)   # lower tail
    z99 = norm_ppf(0.01)
    # No skew/kurtosis -> recovers the Gaussian quantile exactly.
    check("S=K=0 recovers Gaussian", approx(_cornish_fisher_quantile(z95, 0, 0), z95, 1e-12))
    # Positive excess kurtosis fattens the deep tail (99%): more negative quantile => larger VaR.
    check("kurtosis fattens 99% tail", _cornish_fisher_quantile(z99, 0, 3) < z99,
          f"{_cornish_fisher_quantile(z99, 0, 3):.4f} < {z99:.4f}")
    # Negative skew increases left-tail VaR at 95%.
    check("negative skew raises 95% VaR", _cornish_fisher_quantile(z95, -1.0, 0) < z95,
          f"{_cornish_fisher_quantile(z95, -1.0, 0):.4f} < {z95:.4f}")


def verify_shrinkage():
    print("8. Ledoit-Wolf shrinkage sanity")
    # Tiny 6x3 demeaned-ish dataset.
    X = [[0.02, -0.01, 0.03], [-0.01, 0.02, -0.02], [0.03, 0.01, 0.01],
         [-0.02, -0.03, 0.02], [0.01, 0.02, -0.01], [-0.03, 0.01, 0.00]]
    T, n = len(X), len(X[0])
    mean = [sum(X[t][j] for t in range(T)) / T for j in range(n)]
    Xc = [[X[t][j] - mean[j] for j in range(n)] for t in range(T)]
    # S = Xc^T Xc / T
    S = [[sum(Xc[t][i] * Xc[t][j] for t in range(T)) / T for j in range(n)] for i in range(n)]
    m = sum(S[i][i] for i in range(n)) / n
    F = [[m if i == j else 0.0 for j in range(n)] for i in range(n)]
    d2 = sum((S[i][j] - F[i][j]) ** 2 for i in range(n) for j in range(n))
    b2 = 0.0
    for t in range(T):
        for i in range(n):
            for j in range(n):
                b2 += (Xc[t][i] * Xc[t][j] - S[i][j]) ** 2
    b2 /= T * T
    delta = max(0.0, min(1.0, b2 / d2)) if d2 > 0 else 0.0
    sigma = [[delta * F[i][j] + (1 - delta) * S[i][j] for j in range(n)] for i in range(n)]
    check("shrinkage intensity in [0,1]", 0.0 <= delta <= 1.0, f"delta={delta:.4f}")
    off_shrunk = all(abs(sigma[i][j]) <= abs(S[i][j]) + 1e-15
                     for i in range(n) for j in range(n) if i != j)
    check("off-diagonals shrunk toward 0", off_shrunk)


def verify_single_factor_reverse():
    print("9. Reverse stress single-factor paths  s_j = -L/g_j")
    B = [[1.0, 0.0], [0.0, -7.5], [0.5, -4.0]]
    w = [0.5, 0.3, 0.2]
    Bt = transpose(B)
    g = mat_vec(Bt, w)
    L = 0.15
    ok = True
    for j in range(2):
        if abs(g[j]) < 1e-12:
            continue
        s = [0.0, 0.0]
        s[j] = -L / g[j]
        if not approx(vec_dot(g, s), -L, 1e-12):
            ok = False
    check("each single-factor path hits -L", ok, f"g={[round(x,4) for x in g]}")


def main():
    print("=" * 68)
    print("MacroShock — independent formula verification (stdlib only)")
    print("=" * 68)
    verify_volatility()
    verify_var()
    verify_risk_decomposition()
    verify_ols()
    verify_bond_pricing()
    verify_reverse_stress()
    verify_cornish_fisher()
    verify_shrinkage()
    verify_single_factor_reverse()
    print("-" * 68)
    print(f"RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
