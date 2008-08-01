"""
Adaptive numerical evaluation of SymPy expressions, using mpmath
for mathematical functions.
"""

from sympy.mpmath.lib import (from_int, from_rational, fpi, fzero, fcmp,
    normalize, bitcount, round_nearest, to_str, fpow, fone, fpowi, fe,
    fnone, fhalf, fcos, fsin, flog, fatan, fmul, fneg, to_float, fshift,
    fabs, fatan2, fadd, fdiv, flt, dps_to_prec, prec_to_dps, fpos, from_float,
    fnone, to_int, flt)

import sympy.mpmath.libmpc as libmpc
from sympy.mpmath import mpf, mpc, quadts, mp
from sympy.mpmath.specfun import mpf_gamma

import math

from basic import Basic, C, S
from function import Function
from sympify import sympify

LG10 = math.log(10,2)

# Used in a few places as placeholder values to denote exponents and
# precision levels, e.g. of exact numbers. Must be careful to avoid
# passing these to mpmath functions or returning them in final results.
INF = 1e1000
MINUS_INF = -1e1000

# ~= 100 digits. Real men set this to INF.
DEFAULT_MAXPREC = 333

class PrecisionExhausted(ArithmeticError):
    pass

#----------------------------------------------------------------------------#
#                                                                            #
#              Helper functions for arithmetic and complex parts             #
#                                                                            #
#----------------------------------------------------------------------------#

"""
An mpf value tuple is a tuple of integers (sign, man, exp, bc)
representing a floating-point numbers.

A temporary result is a tuple (re, im, re_acc, im_acc) where
re and im are nonzero mpf value tuples representing approximate
numbers, or None to denote exact zeros.

re_acc, im_acc are integers denoting log2(e) where is the estimated
relative accuracy of the respective complex part, but many be anything
if the corresponding complex part is None.

"""

def fastlog(x):
    """Fast approximation of log2(x) for an mpf value tuple x."""
    if not x or x == fzero:
        return MINUS_INF
    # log2(x) ~= exponent + width of mantissa
    # Note: this actually gives ceil(log2(x)), which is a useful
    # feature for interval arithmetic.
    return x[2] + x[3]

def complex_accuracy(result):
    """
    Returns relative accuracy of a complex number with given accuracies
    for the real and imaginary parts. The relative accuracy is defined
    in the complex norm sense as ||z|+|error|| / |z| where error
    is equal to (real absolute error) + (imag absolute error)*i.

    The full expression for the (logarithmic) error can be approximated
    easily by using the max norm to approximate the complex norm.

    In the worst case (re and im equal), this is wrong by a factor
    sqrt(2), or by log2(sqrt(2)) = 0.5 bit.
    """
    re, im, re_acc, im_acc = result
    if not im:
        if not re:
            return INF
        return re_acc
    if not re:
        return im_acc
    re_size = fastlog(re)
    im_size = fastlog(im)
    absolute_error = max(re_size-re_acc, im_size-im_acc)
    relative_error = absolute_error - max(re_size, im_size)
    return -relative_error

def get_abs(expr, prec, options):
    re, im, re_acc, im_acc = evalf(expr, prec+2, options)
    if not re:
        re, re_acc = im, im_acc
    if im:
        return libmpc.mpc_abs((re, im), prec), None, re_acc, None
    else:
        return fabs(re), None, re_acc, None

def get_complex_part(expr, no, prec, options):
    """no = 0 for real part, no = 1 for imaginary part"""
    workprec = prec
    i = 0
    while 1:
        res = evalf(expr, workprec, options)
        value, accuracy = res[no::2]
        if (not value) or accuracy >= prec:
            return value, None, accuracy, None
        workprec += max(30, 2**i)
        i += 1

def evalf_abs(expr, prec, options):
    return get_abs(expr.args[0], prec, options)

def evalf_re(expr, prec, options):
    return get_complex_part(expr.args[0], 0, prec, options)

def evalf_im(expr, prec, options):
    return get_complex_part(expr.args[0], 1, prec, options)

def finalize_complex(re, im, prec):
    assert re and im
    if re == fzero and im == fzero:
        raise ValueError("got complex zero with unknown accuracy")
    size_re = fastlog(re)
    size_im = fastlog(im)
    # Convert fzeros to scaled zeros
    if re == fzero:
        re = fshift(fone, size_im-prec)
        size_re = fastlog(re)
    elif im == fzero:
        im = fshift(fone, size_re-prec)
        size_im = fastlog(im)
    if size_re > size_im:
        re_acc = prec
        im_acc = prec + min(-(size_re - size_im), 0)
    else:
        im_acc = prec
        re_acc = prec + min(-(size_im - size_re), 0)
    return re, im, re_acc, im_acc

def chop_parts(value, prec):
    """
    Chop off tiny real or complex parts.
    """
    re, im, re_acc, im_acc = value
    # Method 1: chop based on absolute value
    if re and (fastlog(re) < -prec+4):
        re, re_acc = None, None
    if im and (fastlog(im) < -prec+4):
        im, im_acc = None, None
    # Method 2: chop if inaccurate and relatively small
    if re and im:
        delta = fastlog(re) - fastlog(im)
        if re_acc < 2 and (delta - re_acc <= -prec+4):
            re, re_acc = None, None
        if im_acc < 2 and (delta - im_acc >= prec-4):
            im, im_acc = None, None
    return re, im, re_acc, im_acc

def check_target(expr, result, prec):
    a = complex_accuracy(result)
    if a < prec:
        raise PrecisionExhausted("Failed to distinguish the expression: \n\n%s\n\n"
            "from zero. Try simplifying the input, using chop=True, or providing "
            "a higher maxprec for evalf" % (expr))

def get_integer_part(expr, no, options):
    """
    With no = 1, computes ceiling(expr)
    With no = -1, computes floor(expr)

    Note: this function either gives the exact result or signals failure.
    """
    ire, iim, ire_acc, iim_acc = evalf(expr, 30, options)
    if ire and iim:
        gap = max(fastlog(ire)-ire_acc, fastlog(iim)-iim_acc)
    elif ire:
        gap = fastlog(ire)-ire_acc
    elif iim:
        gap = fastlog(iim)-iim_acc
    else:
        return None, None, None, None
    if gap >= -10:
        ire, iim, ire_acc, iim_acc = evalf(expr, 30+gap, options)
    if ire: nint_re = int(to_int(ire, round_nearest))
    if iim: nint_im = int(to_int(iim, round_nearest))
    re, im, re_acc, im_acc = None, None, None, None
    if ire:
        e = C.Add(C.re(expr, evaluate=False), -nint_re, evaluate=False)
        re, _, re_acc, _ = evalf(e, 10, options)
        check_target(e, (re, None, re_acc, None), 3)
        #assert (re_acc - fastlog(re)) > 3
        nint_re += int(no*(fcmp(re or fzero, fzero) == no))
        re = from_int(nint_re)
    if iim:
        e = C.Add(C.im(expr, evaluate=False), -nint_im*S.ImaginaryUnit, evaluate=False)
        _, im, _, im_acc = evalf(e, 10, options)
        check_target(e, (im, None, im_acc, None), 3)
        #assert (im_acc - fastlog(im)) > 3
        nint_im += int(no*(fcmp(im or fzero, fzero) == no))
        im = from_int(nint_im)
    return re, im, re_acc, im_acc

def evalf_ceiling(expr, prec, options):
    return get_integer_part(expr.args[0], 1, options)

def evalf_floor(expr, prec, options):
    return get_integer_part(expr.args[0], -1, options)

#----------------------------------------------------------------------------#
#                                                                            #
#                            Arithmetic operations                           #
#                                                                            #
#----------------------------------------------------------------------------#

def add_terms(terms, prec, target_prec):
    """
    Helper for evalf_add. Adds a list of (mpfval, accuracy) terms.
    """
    if len(terms) == 1:
        if not terms[0]:
            # XXX: this is supposed to represent a scaled zero
            return fshift(fone, target_prec), -1
        return terms[0]
    sum_man, sum_exp, absolute_error = 0, 0, MINUS_INF
    for x, accuracy in terms:
        if not x:
            continue
        sign, man, exp, bc = x
        if sign:
            man = -man
        absolute_error = max(absolute_error, bc+exp-accuracy)
        delta = exp - sum_exp
        if exp >= sum_exp:
            if delta > 4*prec:
                sum_man = man
                sum_exp = exp
            else:
                sum_man += man << delta
        else:
            if (-delta) > 4*prec:
                pass
            else:
                sum_man = (sum_man << (-delta)) + man
                sum_exp = exp
    if absolute_error == MINUS_INF:
        return None, None
    if not sum_man:
        # XXX: this is supposed to represent a scaled zero
        return fshift(fone, absolute_error), -1
    if sum_man < 0:
        sum_sign = 1
        sum_man = -sum_man
    else:
        sum_sign = 0
    sum_bc = bitcount(sum_man)
    sum_accuracy = sum_exp + sum_bc - absolute_error
    r = normalize(sum_sign, sum_man, sum_exp, sum_bc, target_prec,
        round_nearest), sum_accuracy
    #print "returning", to_str(r[0],50), r[1]
    return r

def evalf_add(v, prec, options):
    args = v.args
    target_prec = prec
    i = 0

    oldmaxprec = options.get('maxprec', DEFAULT_MAXPREC)
    options['maxprec'] = min(oldmaxprec, 2*prec)

    try:
        while 1:
            terms = [evalf(arg, prec+10, options) for arg in args]
            re, re_accuracy = add_terms([(a[0],a[2]) for a in terms if a[0]], prec, target_prec)
            im, im_accuracy = add_terms([(a[1],a[3]) for a in terms if a[1]], prec, target_prec)
            accuracy = complex_accuracy((re, im, re_accuracy, im_accuracy))
            if accuracy >= target_prec:
                if options.get('verbose'):
                    print "ADD: wanted", target_prec, "accurate bits, got", re_accuracy, im_accuracy
                return re, im, re_accuracy, im_accuracy
            else:
                diff = target_prec - accuracy
                if (prec-target_prec) > options.get('maxprec', DEFAULT_MAXPREC):
                    return re, im, re_accuracy, im_accuracy

                prec = prec + max(10+2**i, diff)
                options['maxprec'] = min(oldmaxprec, 2*prec)
                if options.get('verbose'):
                    print "ADD: restarting with prec", prec
            i += 1
    finally:
        options['maxprec'] = oldmaxprec

# Helper for complex multiplication
# XXX: should be able to multiply directly, and use complex_accuracy
# to obtain the final accuracy
def cmul((a, aacc), (b, bacc), (c, cacc), (d, dacc), prec, target_prec):
    A, Aacc = fmul(a,c,prec), min(aacc, cacc)
    B, Bacc = fmul(fneg(b),d,prec), min(bacc, dacc)
    C, Cacc = fmul(a,d,prec), min(aacc, dacc)
    D, Dacc = fmul(b,c,prec), min(bacc, cacc)
    re, re_accuracy = add_terms([(A, Aacc), (B, Bacc)], prec, target_prec)
    im, im_accuracy = add_terms([(C, Cacc), (D, Cacc)], prec, target_prec)
    return re, im, re_accuracy, im_accuracy

def evalf_mul(v, prec, options):
    args = v.args
    # With guard digits, multiplication in the real case does not destroy
    # accuracy. This is also true in the complex case when considering the
    # total accuracy; however accuracy for the real or imaginary parts
    # separately may be lower.
    acc = prec
    target_prec = prec
    # XXX: big overestimate
    prec = prec + len(args) + 5
    direction = 0
    # Empty product is 1
    man, exp, bc = 1, 0, 1
    direction = 0
    complex_factors = []
    # First, we multiply all pure real or pure imaginary numbers.
    # direction tells us that the result should be multiplied by
    # i**direction
    for arg in args:
        re, im, a, aim = evalf(arg, prec, options)
        if re and im:
            complex_factors.append((re, im, a, aim))
            continue
        elif re:
            s, m, e, b = re
        elif im:
            a = aim
            direction += 1
            s, m, e, b = im
        else:
            return None, None, None, None
        direction += 2*s
        man *= m
        exp += e
        bc += b
        if bc > 3*prec:
            man >>= prec
            exp += prec
        acc = min(acc, a)
    sign = (direction & 2) >> 1
    v = normalize(sign, man, exp, bitcount(man), prec, round_nearest)
    if complex_factors:
        # Multiply first complex number by the existing real scalar
        re, im, re_acc, im_acc = complex_factors[0]
        re = fmul(re, v, prec)
        im = fmul(im, v, prec)
        re_acc = min(re_acc, acc)
        im_acc = min(im_acc, acc)
        # Multiply consecutive complex factors
        complex_factors = complex_factors[1:]
        for wre, wim, wre_acc, wim_acc in complex_factors:
            re, im, re_acc, im_acc = cmul((re, re_acc), (im,im_acc),
                (wre,wre_acc), (wim,wim_acc), prec, target_prec)
        if options.get('verbose'):
            print "MUL: obtained accuracy", re_acc, im_acc, "expected", target_prec
        # multiply by i
        if direction & 1:
            return fneg(im), re, re_acc, im_acc
        else:
            return re, im, re_acc, im_acc
    else:
        # multiply by i
        if direction & 1:
            return None, v, None, acc
        else:
            return v, None, acc, None

def evalf_pow(v, prec, options):
    target_prec = prec
    base, exp = v.args
    # We handle x**n separately. This has two purposes: 1) it is much
    # faster, because we avoid calling evalf on the exponent, and 2) it
    # allows better handling of real/imaginary parts that are exactly zero
    if exp.is_Integer:
        p = exp.p
        # Exact
        if not p:
            return fone, None, prec, None
        # Exponentiation by p magnifies relative error by |p|, so the
        # base must be evaluated with increased precision if p is large
        prec += int(math.log(abs(p),2))
        re, im, re_acc, im_acc = evalf(base, prec+5, options)
        # Real to integer power
        if re and not im:
            return fpowi(re, p, target_prec), None, target_prec, None
        # (x*I)**n = I**n * x**n
        if im and not re:
            z = fpowi(im, p, target_prec)
            case = p % 4
            if case == 0: return z, None, target_prec, None
            if case == 1: return None, z, None, target_prec
            if case == 2: return fneg(z), None, target_prec, None
            if case == 3: return None, fneg(z), None, target_prec
        # General complex number to arbitrary integer power
        re, im = libmpc.mpc_pow_int((re, im), p, prec)
        # Assumes full accuracy in input
        return finalize_complex(re, im, target_prec)

    # TODO: optimize these cases
    #pure_exp = (base is S.Exp1)
    #pure_sqrt = (base is S.Half)

    # Complex or real to a real power
    # We first evaluate the exponent to find its magnitude
    prec += 10
    yre, yim, yre_acc, yim_acc = evalf(exp, prec, options)
    ysize = fastlog(yre)
    # Need to restart if too big
    if ysize > 5:
        prec += ysize
        yre, yim, yre_acc, yim_acc = evalf(exp, prec, options)
    if yim:
        if base is S.Exp1:
            re, im = libmpc.mpc_exp((yre or fzero, yim or fzero), prec)
            return finalize_complex(re, im, target_prec)
        raise NotImplementedError
    xre, xim, xre_acc, yim_acc = evalf(base, prec, options)
    # Complex ** real
    if xim:
        re, im = libmpc.mpc_pow_mpf((xre or fzero, xim), yre, target_prec)
        return finalize_complex(re, im, target_prec)
    # Fractional power of negative real
    elif flt(xre, fzero):
        return None, fpow(fneg(xre), yre, target_prec), None, target_prec
    else:
        return fpow(xre, yre, target_prec), None, target_prec, None




#----------------------------------------------------------------------------#
#                                                                            #
#                            Special functions                               #
#                                                                            #
#----------------------------------------------------------------------------#

def evalf_trig(v, prec, options):
    """
    This function handles sin and cos of real arguments.

    TODO: should also handle tan and complex arguments.
    """
    if v.func is C.cos:
        func = fcos
    elif v.func is C.sin:
        func = fsin
    else:
        raise NotImplementedError
    arg = v.args[0]
    # 20 extra bits is possibly overkill. It does make the need
    # to restart very unlikely
    xprec = prec + 20
    re, im, re_accuracy, im_accuracy = evalf(arg, xprec, options)
    if im:
        raise NotImplementedError
    if not re:
        if v.func is C.cos:
            return fone, None, prec, None
        elif v.func is C.sin:
            return None, None, None, None
        else:
            raise NotImplementedError
    # For trigonometric functions, we are interested in the
    # fixed-point (absolute) accuracy of the argument.
    xsize = fastlog(re)
    # Magnitude <= 1.0. OK to compute directly, because there is no
    # danger of hitting the first root of cos (with sin, magnitude
    # <= 2.0 would actually be ok)
    if xsize < 1:
        return func(re, prec, round_nearest), None, prec, None
    # Very large
    if xsize >= 10:
        xprec = prec + xsize
        re, im, re_accuracy, im_accuracy = evalf(arg, xprec, options)
    # Need to repeat in case the argument is very close to a
    # multiple of pi (or pi/2), hitting close to a root
    while 1:
        y = func(re, prec, round_nearest)
        ysize = fastlog(y)
        gap = -ysize
        accuracy = (xprec - xsize) - gap
        if accuracy < prec:
            if options.get('verbose'):
                print "SIN/COS", accuracy, "wanted", prec, "gap", gap
                print to_str(y,10)
            if xprec > options.get('maxprec', DEFAULT_MAXPREC):
                return y, None, accuracy, None
            xprec += gap
            re, im, re_accuracy, im_accuracy = evalf(arg, xprec, options)
            continue
        else:
            return y, None, prec, None

def evalf_log(expr, prec, options):
    arg = expr.args[0]
    workprec = prec+10
    xre, xim, xacc, _ = evalf(arg, workprec, options)

    if xim:
        # XXX: use get_abs etc instead
        re = evalf_log(C.log(C.abs(arg, evaluate=False), evaluate=False), prec, options)
        im = fatan2(xim, xre, prec)
        return re[0], im, re[2], prec

    imaginary_term = (fcmp(xre, fzero) < 0)

    re = flog(fabs(xre), prec, round_nearest)
    size = fastlog(re)
    if prec - size > workprec:
        # We actually need to compute 1+x accurately, not x
        arg = C.Add(S.NegativeOne,arg,evaluate=False)
        xre, xim, xre_acc, xim_acc = evalf_add(arg, prec, options)
        prec2 = workprec - fastlog(xre)
        re = flog(fadd(xre, fone, prec2), prec, round_nearest)

    re_acc = prec

    if imaginary_term:
        return re, fpi(prec), re_acc, prec
    else:
        return re, None, re_acc, None

def evalf_atan(v, prec, options):
    arg = v.args[0]
    xre, xim, reacc, imacc = evalf(arg, prec+5, options)
    if xim:
        raise NotImplementedError
    return fatan(xre, prec, round_nearest), None, prec, None


#----------------------------------------------------------------------------#
#                                                                            #
#                            High-level operations                           #
#                                                                            #
#----------------------------------------------------------------------------#

def as_mpmath(x, prec, options):
    x = sympify(x)
    if isinstance(x, C.Zero):
        return mpf(0)
    if isinstance(x, C.Infinity):
        return mpf('inf')
    if isinstance(x, C.NegativeInfinity):
        return mpf('-inf')
    # XXX
    re, im, _, _ = evalf(x, prec, options)
    if im:
        return mpc(re or fzero, im)
    return mpf(re)

def do_integral(expr, prec, options):
    func = expr.args[0]
    x, (xlow, xhigh) = expr.args[1][0]
    orig = mp.prec

    oldmaxprec = options.get('maxprec', DEFAULT_MAXPREC)
    options['maxprec'] = min(oldmaxprec, 2*prec)

    try:
        mp.prec = prec+5
        xlow = as_mpmath(xlow, prec+15, options)
        xhigh = as_mpmath(xhigh, prec+15, options)

        # Integration is like summation, and we can phone home from
        # the integrand function to update accuracy summation style
        # Note that this accuracy is inaccurate, since it fails
        # to account for the variable quadrature weights,
        # but it is better than nothing

        have_part = [False, False]
        max_real_term = [MINUS_INF]
        max_imag_term = [MINUS_INF]

        def f(t):
            re, im, re_acc, im_acc = evalf(func, prec+15, {'subs':{x:t}})

            have_part[0] = re or have_part[0]
            have_part[1] = im or have_part[1]

            max_real_term[0] = max(max_real_term[0], fastlog(re))
            max_imag_term[0] = max(max_imag_term[0], fastlog(im))

            if im:
                return mpc(re or fzero, im)
            return mpf(re or fzero)

        result, quadrature_error = quadts(f, xlow, xhigh, error=1)
        quadrature_error = fastlog(quadrature_error._mpf_)

    finally:
        options['maxprec'] = oldmaxprec
        mp.prec = orig

    if have_part[0]:
        re = result.real._mpf_
        if re == fzero:
            re = fshift(fone, min(-prec,-max_real_term[0],-quadrature_error))
            re_acc = -1
        else:
            re_acc = -max(max_real_term[0]-fastlog(re)-prec, quadrature_error)
    else:
        re, re_acc = None, None

    if have_part[1]:
        im = result.imag._mpf_
        if im == fzero:
            im = fshift(fone, min(-prec,-max_imag_term[0],-quadrature_error))
            im_acc = -1
        else:
            im_acc = -max(max_imag_term[0]-fastlog(im)-prec, quadrature_error)
    else:
        im, im_acc = None, None

    result = re, im, re_acc, im_acc
    return result

def evalf_integral(expr, prec, options):
    workprec = prec
    i = 0
    maxprec = options.get('maxprec', INF)
    while 1:
        result = do_integral(expr, workprec, options)
        accuracy = complex_accuracy(result)
        if accuracy >= prec or workprec >= maxprec:
            return result
        workprec += prec - max(-2**i, accuracy)
        i += 1

#----------------------------------------------------------------------------#
#                                                                            #
#                            Symbolic interface                              #
#                                                                            #
#----------------------------------------------------------------------------#

def evalf_symbol(x, prec, options):
    val = options['subs'][x]
    if isinstance(val, mpf):
        if not val:
            return None, None, None, None
        return val._mpf_, None, prec, None
    else:
        if not '_cache' in options:
            options['_cache'] = {}
        cache = options['_cache']
        cached, cached_prec = cache.get(x.name, (None, MINUS_INF))
        if cached_prec >= prec:
            return cached
        v = evalf(sympify(val), prec, options)
        cache[x.name] = (v, prec)
        return v

evalf_table = None

def _create_evalf_table():
    global evalf_table
    evalf_table = {
    C.Symbol : evalf_symbol,
    C.Real : lambda x, prec, options: (x._mpf_, None, prec, None),
    C.Rational : lambda x, prec, options: (from_rational(x.p, x.q, prec), None, prec, None),
    C.Integer : lambda x, prec, options: (from_int(x.p, prec), None, prec, None),
    C.Zero : lambda x, prec, options: (None, None, prec, None),
    C.One : lambda x, prec, options: (fone, None, prec, None),
    C.Half : lambda x, prec, options: (fhalf, None, prec, None),
    C.Pi : lambda x, prec, options: (fpi(prec), None, prec, None),
    C.Exp1 : lambda x, prec, options: (fe(prec), None, prec, None),
    C.ImaginaryUnit : lambda x, prec, options: (None, fone, None, prec),
    C.NegativeOne : lambda x, prec, options: (fnone, None, prec, None),

    C.exp : lambda x, prec, options: evalf_pow(C.Pow(S.Exp1, x.args[0],
        evaluate=False), prec, options),

    C.cos : evalf_trig,
    C.sin : evalf_trig,

    C.Add : evalf_add,
    C.Mul : evalf_mul,
    C.Pow : evalf_pow,

    C.log : evalf_log,
    C.atan : evalf_atan,
    C.abs : evalf_abs,

    C.re : evalf_re,
    C.im : evalf_im,
    C.floor : evalf_floor,
    C.ceiling : evalf_ceiling,

    C.Integral : evalf_integral,
    }

def evalf(x, prec, options):
    try:
        r = evalf_table[x.func](x, prec, options)
    except KeyError:
        #r = finalize_complex(x._eval_evalf(prec)._mpf_, fzero, prec)
        try:
            # Fall back to ordinary evalf if possible
            if 'subs' in options:
                x = x.subs(options['subs'])
            r = x._eval_evalf(prec)._mpf_, None, prec, None
        except AttributeError:
            raise NotImplementedError
    if options.get("verbose"):
        print "### input", x
        print "### output", to_str(r[0] or fzero, 50)
        #print "### raw", r[0], r[2]
        print
    if options.get("chop"):
        r = chop_parts(r, prec)
    if options.get("strict"):
        check_target(x, r, prec)
    return r

def Basic_evalf(x, n=15, **options):
    """
    Evaluate the given formula to an accuracy of n digits.
    Optional keyword arguments:

        subs=<dict>
            Substitute numerical values for symbols, e.g.
            subs={x:3, y:1+pi}.

        maxprec=N
            Allow a maximum temporary working precision of N digits
            (default=100)

        chop=<bool>
            Replace tiny real or imaginary parts in subresults
            by exact zeros (default=False)

        strict=<bool>
            Raise PrecisionExhausted if any subresult fails to evaluate
            to full accuracy, given the available maxprec
            (default=False)

        verbose=<bool>
            Print debug information (default=False)

    """
    if not evalf_table:
        _create_evalf_table()
    prec = dps_to_prec(n)
    if 'maxprec' in options:
        options['maxprec'] = int(options['maxprec']*LG10)
    else:
        options['maxprec'] = max(prec, DEFAULT_MAXPREC)
    try:
        result = evalf(x, prec+4, options)
    except NotImplementedError:
        # Fall back to the ordinary evalf
        v = x._eval_evalf(prec)
        if v is None:
            return x
        try:
            # If the result is numerical, normalize it
            result = evalf(v, prec, options)
        except:
            # Probably contains symbols or unknown functions
            return v
    re, im, re_acc, im_acc = result
    if re:
        p = max(min(prec, re_acc), 1)
        #re = fpos(re, p, round_nearest)
        re = C.Real._new(re, p)
    else:
        re = S.Zero
    if im:
        p = max(min(prec, im_acc), 1)
        #im = fpos(im, p, round_nearest)
        im = C.Real._new(im, p)
        return re + im*S.ImaginaryUnit
    else:
        return re

Basic.evalf = Basic.n = Basic_evalf

def N(x, n=15, **options):
    return sympify(x).evalf(n, **options)