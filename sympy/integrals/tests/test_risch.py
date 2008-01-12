
from sympy import *
from sympy.integrals.risch import heurisch
from sympy.utilities.pytest import XFAIL
from py.test import skip

x, y = symbols('xy')

def test_heurisch_polynomials():
    assert heurisch(1, x) == x
    assert heurisch(x, x) == x**2/2
    assert heurisch(x**17, x) == x**18/18

def test_heurisch_fractions():
    assert heurisch(1/x, x) == log(x)
    assert heurisch(1/(2 + x), x) == log(x + 2)

    assert heurisch(5*x**5/(2*x**6 + 5), x) == 5*log(5 + 2*x**6) / 12

    assert heurisch(1/x**2, x) == -1/x
    assert heurisch(-1/x**5, x) == 1/(4*x**4)

def test_heurisch_log():
    assert heurisch(log(x), x) == x*log(x) - x
    assert heurisch(log(3*x), x) == x*log(3*x) - x
    assert heurisch(log(x**2), x) in [x*log(x**2) - 2*x, 2*x*log(x) - 2*x]

def test_heurisch_exp():
    assert heurisch(exp(x), x) == exp(x)
    assert heurisch(exp(-x), x) == -exp(-x)
    assert heurisch(exp(17*x), x) == exp(17*x) / 17
    assert heurisch(x*exp(x), x) == x*exp(x) - exp(x)
    assert heurisch(x*exp(x**2), x) == exp(x**2) / 2

    assert heurisch(exp(-x**2), x) is None

def test_heurisch_trigonometric():
    assert heurisch(sin(x), x) == -cos(x)
    assert heurisch(cos(x), x) == sin(x)

    assert heurisch(sin(x)*sin(y), x) == -cos(x)*sin(y)
    assert heurisch(sin(x)*sin(y), y) == -cos(y)*sin(x)

    # gives sin(x) in answer when run via setup.py and cos(x) when via py.test
    assert heurisch(sin(x)*cos(x), x) in [sin(x)**2 / 2, -cos(x)**2 / 2]
    assert heurisch(cos(x)/sin(x), x) == log(sin(x))

    assert heurisch(x*sin(7*x), x) == sin(7*x) / 49 - x*cos(7*x) / 7
    assert heurisch(1/pi/4 * x**2*cos(x), x) == 1/pi/4*(x**2*sin(x) - 2*sin(x) + 2*x*cos(x))

def test_heurisch_hyperbolic():
    assert heurisch(sinh(x), x) == cosh(x)
    assert heurisch(cosh(x), x) == sinh(x)

    assert heurisch(x*sinh(x), x) == x*cosh(x) - sinh(x)
    assert heurisch(x*cosh(x), x) == x*sinh(x) - cosh(x)

def test_heurisch_mixed():
    assert heurisch(sin(x)*exp(x), x) == exp(x)*sin(x)/2 - exp(x)*cos(x)/2

def test_heurisch_radicals():
    assert heurisch(x**Rational(-1,2), x) == 2*x**Rational(1,2)
    assert heurisch(x**Rational(-3,2), x) == -2*x**Rational(-1,2)
    assert heurisch(x**Rational(3,2), x) == 2*x**Rational(5,2) / 5

    assert heurisch(sin(x)*sqrt(cos(x)), x) == -2*cos(x)**Rational(3,2) / 3
    assert heurisch(sin(y*sqrt(x)), x) == 2*y**(-2)*sin(y*x**S.Half) - \
                                          2*x**S.Half*cos(y*x**S.Half)/y

def test_heurisch_special():
    assert heurisch(erf(x), x) == x*erf(x) + exp(-x**2)/sqrt(pi)
    assert heurisch(exp(-x**2)*erf(x), x) == sqrt(pi)*erf(x)**2 / 4

def test_heurisch_symbolic_coeffs():
    assert heurisch(1/(x+y), x)         == log(x+y)
    assert heurisch(1/(x+sqrt(2)), x)   == log(x+sqrt(2))
    assert heurisch(1/(x**2+y), x)      == I*y**(-S.Half)*log(x + (-y)**S.Half)/2 - \
                                           I*y**(-S.Half)*log(x - (-y)**S.Half)/2

def test_issue510():
    assert integrate(1/(x * (1 + log(x)**2))) == I*log(I+log(x))/2 - \
            I*log(-I+log(x))/2

    # Following won't work as long as polynomials have functionality like:
    # "XXX this will not work for sin(x), sqrt(2), etc..."

    # assert heurisch(1/(x+sin(y)), x)    == log(x+sin(y))

### These are examples from the Poor Man's Integrator
### http://www-sop.inria.fr/cafe/Manuel.Bronstein/pmint/examples/
#
# NB: correctness assured as ratsimp(diff(g,x) - f) == 0 in maxima
# SymPy is unable to do it :(

# Besides, they are skipped(), because they take too much time to execute.

@XFAIL
def test_pmint_rat():
    skip('takes too much time')
    f = (x**7-24*x**4-4*x**2+8*x-8) / (x**8+6*x**6+12*x**4+8*x**2)
    g = (4 + 8*x**2 + 6*x + 3*x**3) / (x*(x**4 + 4*x**2 + 4))  +  log(x)

    assert heurisch(f, x) == g


@XFAIL
def test_pmint_trig():
    skip('takes too much time')
    f = (x-tan(x)) / tan(x)**2  +  tan(x)
    g = (-x - tan(x)*x**2 / 2) / tan(x)  +  log(1+tan(x)**2) / 2

    assert heurisch(f, x) == g


@XFAIL
def test_pmint_logexp():
    skip('takes too much time')
    f = (1+x+x*exp(x))*(x+log(x)+exp(x)-1)/(x+log(x)+exp(x))**2/x
    g = 1/(x+log(x)+exp(x)) + log(x + log(x) + exp(x))

    assert heurisch(f, x) == g


@XFAIL
def test_pmint_erf():
    skip('takes too much time')
    f = exp(-x**2)*erf(x)/(erf(x)**3-erf(x)**2-erf(x)+1)
    g = sqrt(pi)/4 * (-1/(erf(x)-1) - log(erf(x)+1)/2 + log(erf(x)-1)/2)

    assert heurisch(f, x) == g


# TODO: convert the rest of PMINT tests:
# - Airy
# - Bessel
# - Whittaker
# - LambertW
# - Wright omega
