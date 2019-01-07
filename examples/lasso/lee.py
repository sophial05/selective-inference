import functools

import numpy as np
from scipy.stats import norm as ndist

import regreg.api as rr

from selection.tests.instance import gaussian_instance
from selection.algorithms.lasso import lasso

from learn_selection.core import (infer_general_target,
                                  split_sampler, 
                                  normal_sampler,
                                  logit_fit,
                                  repeat_selection,
                                  probit_fit)

def simulate(n=200, p=100, s=10, signal=(0.5, 1), sigma=2, alpha=0.1):

    # description of statistical problem

    X, y, truth = gaussian_instance(n=n,
                                    p=p, 
                                    s=s,
                                    equicorrelated=False,
                                    rho=0.5, 
                                    sigma=sigma,
                                    signal=signal,
                                    random_signs=True,
                                    scale=False)[:3]

    dispersion = sigma**2

    S = X.T.dot(y)
    covS = dispersion * X.T.dot(X)
    smooth_sampler = normal_sampler(S, covS)
    splitting_sampler = split_sampler(X * y[:, None], covS)

    def meta_algorithm(XTX, XTXi, lam, sampler):

        p = XTX.shape[0]
        success = np.zeros(p)

        loss = rr.quadratic_loss((p,), Q=XTX)
        pen = rr.l1norm(p, lagrange=lam)

        scale = 0.
        noisy_S = sampler(scale=scale)
        loss.quadratic = rr.identity_quadratic(0, 0, -noisy_S, 0)
        problem = rr.simple_problem(loss, pen)
        soln = problem.solve(max_its=100, tol=1.e-10)
        success += soln != 0
        return set(np.nonzero(success)[0])

    XTX = X.T.dot(X)
    XTXi = np.linalg.inv(XTX)
    resid = y - X.dot(XTXi.dot(X.T.dot(y)))
    dispersion = np.linalg.norm(resid)**2 / (n-p)
                         
    lam = 4. * np.sqrt(n)
    selection_algorithm = functools.partial(meta_algorithm, XTX, XTXi, lam)

    # run selection algorithm

    success_params = (1, 1)

    observed_set = repeat_selection(selection_algorithm, splitting_sampler, *success_params)

    # find the target, based on the observed outcome

    # we just take the first target  

    pivots, covered, lengths, pvalues = [], [], [], []
    lower, upper = [], []
    naive_pvalues, naive_pivots, naive_covered, naive_lengths =  [], [], [], []

    L = lasso.gaussian(X, y, lam)
    L.fit()
    summaryL = None

    targets = []

    observed_list = L.active

    if len(observed_set) > 0:
        Xpi = np.linalg.pinv(X[:,observed_list])
        final_target = Xpi.dot(X.dot(truth))
        summaryL = L.summary(truth=final_target, compute_intervals=True, level=1-alpha)
        summaryL0 = L.summary(compute_intervals=False)

    for jdx, idx in enumerate(observed_list[:1]):
        print("variable: ", idx, "total selected: ", len(observed_set))

        Xpi = np.linalg.pinv(X[:,observed_list])
        linfunc = Xpi[jdx]
        observed_target = np.array([linfunc.dot(y)])

        sel_dispersion = np.linalg.norm(y - X[:,observed_list].dot(Xpi.dot(y)))**2 / (n - len(observed_list))
        cov_target = np.array([[np.linalg.norm(linfunc)**2 * sel_dispersion]])
        cross_cov = X.T.dot(linfunc).reshape((-1,1)) * sel_dispersion
        true_target = final_target[jdx]

        (pivot, 
         interval,
         pvalue,
         _) = infer_general_target(selection_algorithm,
                                   observed_set,
                                   splitting_sampler,
                                   observed_target,
                                   cross_cov,
                                   cov_target,
                                   hypothesis=[true_target],
                                   fit_probability=probit_fit,
                                   alpha=alpha,
                                   B=1000)[0]

        pvalues.append(pvalue)
        pivots.append(pivot)
        covered.append((interval[0] < true_target) * (interval[1] > true_target))
        lengths.append(interval[1] - interval[0])

        target_sd = np.sqrt(cov_target[0, 0])
        quantile = ndist.ppf(1 - 0.5 * alpha)
        naive_interval = (observed_target - quantile * target_sd, observed_target + quantile * target_sd)

        naive_pivot = np.squeeze((1 - ndist.cdf((observed_target - true_target) / target_sd)))
        naive_pivot = 2 * min(naive_pivot, 1 - naive_pivot)
        naive_pivots.append(naive_pivot)

        naive_pvalue = np.squeeze((1 - ndist.cdf(observed_target / target_sd)))
        naive_pvalue = 2 * min(naive_pvalue, 1 - naive_pvalue)
        naive_pvalues.append(naive_pvalue)

        naive_covered.append(np.squeeze((naive_interval[0] < true_target) * (naive_interval[1] > true_target)))
        naive_lengths.append(np.squeeze(naive_interval[1] - naive_interval[0]))
        lower.append(interval[0])
        upper.append(interval[1])

    if summaryL is not None:
        lee_pivots = summaryL['pval'][:1]
        lee_pvalues = summaryL0['pval'][:1]
        lee_lower = summaryL['lower_confidence'][:1]
        lee_upper = summaryL['upper_confidence'][:1]
        lee_lengths = lee_upper - lee_lower
        lee_covered = [(l < t) * (t < u) for l, u, t in zip(lee_lower, lee_upper, final_target)]
    else:
        lee_pivots = lee_pvalues = lee_lower = lee_upper = lee_lengths = lee_covered = []

    if len(pvalues) > 0:
        return pd.DataFrame({'pivot':pivots,
                             'pvalue':pvalues,
                             'coverage':covered,
                             'length':lengths,
                             'naive_pivot':naive_pivots,
                             'naive_coverage':naive_covered,
                             'naive_length':naive_lengths,
                             'lee_pivot':lee_pivots,
                             'lee_pvalue':lee_pvalues,
                             'lee_length':lee_lengths,
                             'lee_upper':lee_upper,
                             'lee_lower':lee_lower,
                             'upper':upper,
                             'lower':lower,
                             'lee_coverage':lee_covered,
#                             'target':final_target,
                             })


if __name__ == "__main__":
    import statsmodels.api as sm
    import matplotlib.pyplot as plt
    import pandas as pd

    U = np.linspace(0, 1, 101)
    plt.clf()

    for i in range(500):
        df = simulate()
        csvfile = 'lee.csv'

        if df is not None and i % 2 == 1 and i > 0:

            try:
                df = pd.concat([df, pd.read_csv(csvfile)])
            except FileNotFoundError:
                pass

            if len(df['pivot']) > 0:

                print("selective:", np.mean(df['pivot']), np.std(df['pivot']), np.mean(df['length']), np.std(df['length']), np.mean(df['coverage']))
                print("lee:", np.mean(df['lee_pivot']), np.std(df['lee_pivot']), np.mean(df['lee_length']), np.std(df['lee_length']), np.mean(df['lee_coverage']))
                print("naive:", np.mean(df['naive_pivot']), np.std(df['naive_pivot']), np.mean(df['naive_length']), np.std(df['naive_length']), np.mean(df['naive_coverage']))

                print("len ratio selective divided by naive:", np.mean(np.array(df['length']) / np.array(df['naive_length'])))
                print("len ratio selective divided by lee:", np.mean(np.array(df['length']) / np.array(df['lee_length'])))

                plt.clf()
                U = np.linspace(0, 1, 101)
                plt.plot(U, sm.distributions.ECDF(df['pivot'])(U), 'r', label='Selective', linewidth=3)
                plt.plot(U, sm.distributions.ECDF(df['naive_pivot'])(U), 'b', label='Naive', linewidth=3)
                plt.plot(U, sm.distributions.ECDF(df['lee_pivot'][~np.isnan(df['lee_pivot'])])(U), 'g', label='Lee', linewidth=3)
                plt.legend()
                plt.plot([0,1], [0,1], 'k--', linewidth=2)
                plt.savefig(csvfile[:-4] + '.pdf')

                plt.clf()
                plt.scatter(df['naive_length'], df['length'])
                plt.scatter(df['naive_length'], df['lee_length'])
                plt.savefig(csvfile[:-4] + '_lengths.pdf')

            df.to_csv(csvfile, index=False)
