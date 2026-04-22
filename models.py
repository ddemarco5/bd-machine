from enum import Enum
import numpy as np
from scipy.optimize import curve_fit,root_scalar

# Power function that seems to best fit CRF to bitrate relationship
def power_function(x,a,b):
    return a * x **b

# Function for linear equation
def linear_function(x,a,b):
    return a * x + b

# Function to calculate R^2
def calculate_r_squared(y_observed, y_predicted):
    ss_res = np.sum((y_observed - y_predicted) ** 2)        # Sum of squares of residuals
    ss_tot = np.sum((y_observed - np.mean(y_observed)) ** 2) # Total sum of squares
    return 1 - (ss_res / ss_tot)

def fit_power_function(x_data, y_data):
    # Fit the power function to the data
    params, _ = curve_fit(power_function, x_data, y_data)
    print(f"Fitted Power Curve: y = {params[0]:.2f} x^{params[1]:.2f}")
    r = calculate_r_squared(y_data, power_function(x_data, *params))
    print(f"r^2: {r}")
    return params[0],params[1],r

def fit_linear_function(x_data, y_data):
    # Fit the power function to the data
    params, _ = curve_fit(linear_function, x_data, y_data)
    print(f"Fitted Linear eq : y = {params[0]:.2f} x + {params[1]:.2f}")
    r = calculate_r_squared(y_data, linear_function(x_data, *params))
    print(f"r^2: {r}")
    return params[0],params[1],r

class ModelType(Enum):
    LINEAR = linear_function
    POWER = power_function


class Model:
    def __init__(self, type: ModelType, maxsize=None):
        self.modeltype = type
        self.maxsize = maxsize
        self.crf_data = np.array([])
        self.bitrate_data = np.array([])
        self.params = [0] * 2
        self.r_squared = None
        
    def add_data_point(self, crf, bitrate) -> None:
        print(f"Adding data point crf:{crf}, bitrate:{bitrate}")
        # Trim our older (farther) points to keep estimate very accurate
        if self.maxsize and len(self.crf_data) >= self.maxsize:
            self.crf_data = self.crf_data[1:]
            self.bitrate_data = self.bitrate_data[1:]
            print("trimmed some crf data")
        self.crf_data = np.append(self.crf_data, crf)
        self.bitrate_data = np.append(self.bitrate_data, bitrate)
        # re-fit our curve and re-calculate r^2
        if (self.modeltype is ModelType.LINEAR) and (len(self.crf_data) >= 2):
            print("Enough data to fit linear model")
            try:
                self.params[0], self.params[1], self.r_squared = fit_linear_function(self.crf_data, self.bitrate_data)
            except Exception as e:
                print(f"An error occurred during the linear fit function: {e}")
        elif (self.modeltype is ModelType.POWER) and (len(self.crf_data) >= 4):
            print("Enough data to fit power model")
            try:
                self.params[0], self.params[1], self.r_squared = fit_power_function(self.crf_data, self.bitrate_data)
            except Exception as e:
                print(f"An error occurred during the power fit function: {e}")
        else:
            print("Not enough data to fit function yet")
            
    def crf_given_bitrate(self, bitrate):
        def equation_to_solve(x):
            return self.modeltype(x, self.params[0], self.params[1]) - bitrate

        # Use root_scalar to solve for x; set initial bracket based on known x range
        solution = root_scalar(equation_to_solve, bracket=[0.1, 1000], method='brentq')
        
        if solution.converged:
            return solution.root
        else:
            raise ValueError("Root finding did not converge")
        
    def bitrate_given_crf(self, crf):
        return self.modeltype(crf, self.params[0], self.params[1])