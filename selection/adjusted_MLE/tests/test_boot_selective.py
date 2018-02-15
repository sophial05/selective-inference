from __future__ import print_function
import numpy as np, sys

import regreg.api as rr
from selection.tests.instance import gaussian_instance
from scipy.stats import norm as ndist
from selection.randomized.api import randomization
from selection.adjusted_MLE.selective_MLE import M_estimator_map, solve_UMVU
from statsmodels.distributions.empirical_distribution import ECDF
import selection.constraints.affine as AC

from rpy2.robjects.packages import importr
from rpy2 import robjects
from scipy.stats import t as tdist

glmnet = importr('glmnet')
import rpy2.robjects.numpy2ri

rpy2.robjects.numpy2ri.activate()

def glmnet_sigma(X, y):
    robjects.r('''
                glmnet_cv = function(X,y){
                y = as.matrix(y)
                X = as.matrix(X)

                out = cv.glmnet(X, y, standardize=FALSE, intercept=FALSE)
                lam_minCV = out$lambda.min
                return(lam_minCV)
                }''')

    try:
        lambda_cv_R = robjects.globalenv['glmnet_cv']
        n, p = X.shape
        r_X = robjects.r.matrix(X, nrow=n, ncol=p)
        r_y = robjects.r.matrix(y, nrow=n, ncol=1)

        lam_minCV = lambda_cv_R(r_X, r_y)
        return lam_minCV
    except:
        return 0.75 * np.mean(np.fabs(np.dot(X.T, np.random.standard_normal((n, 2000)))).max(0))

def boot_pivot_approx_var(n=100, p=50, s=5, signal=5., B=1000, lam_frac=1., randomization_scale=1., sigma= 1.):

    while True:
        X, y, beta, nonzero, sigma = gaussian_instance(n=n, p=p, s=s, rho=0.2, signal=signal, sigma=sigma,
                                                       random_signs=True, equicorrelated=False)
        n, p = X.shape
        sigma_est = np.std(y) / np.sqrt(2.)
        lam = lam_frac * np.mean(np.fabs(np.dot(X.T, np.random.standard_normal((n, 2000)))).max(0)) * sigma_est
        #lam = glmnet_sigma(X, y)

        loss = rr.glm.gaussian(X, y)
        epsilon = 1./np.sqrt(n)
        W = np.ones(p) * lam
        penalty = rr.group_lasso(np.arange(p),
                                 weights=dict(zip(np.arange(p), W)), lagrange=1.)

        randomizer = randomization.isotropic_gaussian((p,), scale=randomization_scale)
        M_est = M_estimator_map(loss, epsilon, penalty, randomizer, randomization_scale=randomization_scale, sigma=sigma_est)

        M_est.solve_map()
        active = M_est._overall

        true_target = np.linalg.inv(X[:, active].T.dot(X[:, active])).dot(X[:, active].T).dot(X.dot(beta))
        nactive = np.sum(active)
        print("number of variables selected by LASSO", nactive)

        if nactive > 0:
            approx_MLE, var, mle_map, implied_cov, implied_mean, _ = solve_UMVU(M_est.target_transform,
                                                                                M_est.opt_transform,
                                                                                M_est.target_observed,
                                                                                M_est.feasible_point,
                                                                                M_est.target_cov,
                                                                                M_est.randomizer_precision)

            A = np.hstack([np.zeros((nactive, nactive)), -np.identity(nactive)])
            b = np.zeros(nactive)
            con = AC.constraints(A, b, covariance=implied_cov, mean= implied_mean)
            sample = AC.sample_from_constraints(con, np.ones(2*nactive), ndraw=B, burnin=300)
            boot_pivot = np.zeros((B, nactive))
            boot_mle_vec = np.zeros((B, nactive))
            for b in range(B):
                boot_mle = mle_map((sample[b,:])[:nactive])
                boot_pivot[b, :] = np.true_divide(boot_mle[0] - approx_MLE, np.sqrt(np.diag(boot_mle[1])))
                boot_mle_vec[b, :] = boot_mle[0]
            break

    return boot_pivot.reshape((B*nactive,)), boot_pivot.mean(0).sum()/nactive, boot_pivot.std(0), \
           np.true_divide(approx_MLE - true_target, boot_pivot.std(0)), np.true_divide(approx_MLE - true_target, boot_mle_vec.std(0)),\
           (approx_MLE - true_target).sum() / float(nactive)


if __name__ == "__main__":
    import matplotlib.pyplot as plt

    ndraw = 50
    bias = 0.
    pivot_obs_info = []
    pivot_mle = []

    for i in range(ndraw):
        approx = boot_pivot_approx_var(n=2000, p=4000, s=20, signal=3.5, B=2000)
        if approx is not None:
            pivot_boot = approx[3]
            mle_boot = approx[4]
            bias += approx[5]

            for j in range(pivot_boot.shape[0]):
                pivot_obs_info.append(pivot_boot[j])
                pivot_mle.append(mle_boot[j])

        sys.stderr.write("iteration completed" + str(i) + "\n")
        sys.stderr.write("overall_bias" + str(bias / float(i + 1)) + "\n")

    plt.clf()
    ecdf_boot = ECDF(ndist.cdf(np.asarray(pivot_obs_info)))
    ecdf_mle = ECDF(ndist.cdf(np.asarray(pivot_mle)))
    grid = np.linspace(0, 1, 101)
    #print("ecdf", ecdf_boot(grid))
    plt.plot(grid, ecdf_boot(grid), c='blue', marker='^')
    plt.plot(grid, ecdf_mle(grid), c='red', marker='^')
    plt.plot(grid, grid, 'k--')
    #plt.show()
    plt.savefig("/Users/snigdhapanigrahi/Desktop/selective_Boot_pivot_n2000_p4000_amp3.5_rho_0.2_sigma1.png")