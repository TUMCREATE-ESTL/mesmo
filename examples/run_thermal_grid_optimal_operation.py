"""Example script for setting up and solving a thermal grid optimal operation problem."""

import numpy as np
import os
import pandas as pd
import pyomo.environ as pyo

import cobmo.database_interface
import fledge.config
import fledge.data_interface
import fledge.der_models
import fledge.thermal_grid_models
import fledge.utils


def main():

    # Settings.
    scenario_name = 'singapore_tanjongpagar'
    results_path = (
        os.path.join(
            fledge.config.config['paths']['results'],
            f'run_thermal_grid_optimal_operation_{fledge.config.get_timestamp()}'
        )
    )

    # Instantiate results directory.
    os.mkdir(results_path)

    # Recreate / overwrite database, to incorporate changes in the CSV files.
    fledge.data_interface.recreate_database()
    cobmo.database_interface.recreate_database()

    # Obtain data.
    scenario_data = fledge.data_interface.ScenarioData(scenario_name)
    price_data = fledge.data_interface.PriceData(scenario_name)

    # Obtain price timeseries.
    price_type = 'singapore_wholesale'
    price_timeseries = price_data.price_timeseries_dict[price_type]

    # Obtain models.
    thermal_grid_model = fledge.thermal_grid_models.ThermalGridModel(scenario_name)
    thermal_power_flow_solution = fledge.thermal_grid_models.ThermalPowerFlowSolution(thermal_grid_model)
    linear_thermal_grid_model = (
        fledge.thermal_grid_models.LinearThermalGridModel(
            thermal_grid_model,
            thermal_power_flow_solution
        )
    )
    der_model_set = fledge.der_models.DERModelSet(scenario_name)

    # Instantiate optimization problem.
    optimization_problem = pyo.ConcreteModel()

    # Define thermal grid model variables.
    linear_thermal_grid_model.define_optimization_variables(
        optimization_problem,
        scenario_data.timesteps
    )

    # Define thermal grid model constraints.
    node_head_vector_minimum = 1.5 * thermal_power_flow_solution.node_head_vector
    branch_flow_vector_maximum = 1.5 * thermal_power_flow_solution.branch_flow_vector
    linear_thermal_grid_model.define_optimization_constraints(
        optimization_problem,
        scenario_data.timesteps,
        node_head_vector_minimum=node_head_vector_minimum,
        branch_flow_vector_maximum=branch_flow_vector_maximum
    )

    # Define DER variables.
    der_model_set.define_optimization_variables(
        optimization_problem
    )

    # Define DER constraints.
    der_model_set.define_optimization_constraints(
        optimization_problem,
        thermal_grid_model=thermal_grid_model,
        thermal_power_flow_solution=thermal_power_flow_solution
    )

    # Define objective (district cooling plant operation cost minimization).
    linear_thermal_grid_model.define_optimization_objective(
        optimization_problem,
        price_timeseries,
        scenario_data.timesteps
    )

    # Solve optimization problem.
    optimization_problem.dual = pyo.Suffix(direction=pyo.Suffix.IMPORT)
    optimization_solver = pyo.SolverFactory(fledge.config.config['optimization']['solver_name'])
    optimization_result = optimization_solver.solve(optimization_problem, tee=fledge.config.config['optimization']['show_solver_output'])
    try:
        assert optimization_result.solver.termination_condition is pyo.TerminationCondition.optimal
    except AssertionError:
        raise AssertionError(f"Solver termination condition: {optimization_result.solver.termination_condition}")
    # optimization_problem.display()

    # Obtain results.
    results = (
        linear_thermal_grid_model.get_optimization_results(
            optimization_problem,
            scenario_data.timesteps,
            in_per_unit=True,
            with_mean=True
        )
    )

    # Print results.
    print(results)

    # Store results as CSV.
    results.to_csv(results_path)

    # Obtain DLMPs.
    dlmps = (
        linear_thermal_grid_model.get_optimization_dlmps(
            optimization_problem,
            price_timeseries,
            scenario_data.timesteps
        )
    )

    # Print DLMPs.
    print(dlmps)

    # Store DLMPs as CSV.
    dlmps.to_csv(results_path)

    # Print results path.
    print("Results are stored in: " + results_path)


if __name__ == "__main__":
    main()
