import numpy as np
import pandas as pd
import scipy.sparse as sp
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

pd.options.plotting.backend = "matplotlib"
import mesmo


def main():
    # TODO: Currently not working. Review limits below.

    scenario_name = 'polimi_test_case'
    # strategic_scenario = True
    admm_rho = 1e-1
    radius = 1
    # results_path = mesmo.utils.get_results_path(__file__, scenario_name)

    # Recreate / overwrite database, to incorporate changes in the CSV files.
    mesmo.data_interface.recreate_database()

    # Obtain data.
    scenario_data = mesmo.data_interface.ScenarioData(scenario_name)
    price_data = mesmo.data_interface.PriceData(scenario_name
                                                # , price_type='singapore_wholesale'
                                                )
    # Obtain models.
    electric_grid_model = mesmo.electric_grid_models.ElectricGridModelDefault(scenario_name)
    power_flow_solution = mesmo.electric_grid_models.PowerFlowSolutionFixedPoint(electric_grid_model)
    linear_electric_grid_model_set = (
        mesmo.electric_grid_models.LinearElectricGridModelSet(
            electric_grid_model,
            power_flow_solution
        )
    )
    der_model_set = mesmo.der_models.DERModelSet(scenario_name)

    # Instantiate centralized optimization problem.
    optimization_baseline = mesmo.utils.OptimizationProblem()

    max_branch_power = 1

    # Define electric grid problem.
    # TODO: Review limits.
    node_voltage_magnitude_vector_minimum = 0.95 * np.abs(electric_grid_model.node_voltage_vector_reference)
    node_voltage_magnitude_vector_maximum = 1.05 * np.abs(electric_grid_model.node_voltage_vector_reference)
    branch_power_magnitude_vector_maximum = max_branch_power * electric_grid_model.branch_power_vector_magnitude_reference

    grid_cost_coefficient = 1

    der_model_set.define_optimization_problem(optimization_baseline,
                                              price_data,
                                              state_space_model=True,
                                              kkt_conditions=False,
                                              grid_cost_coefficient=grid_cost_coefficient
                                              )

    linear_electric_grid_model_set.define_optimization_problem(
        optimization_baseline,
        price_data,
        node_voltage_magnitude_vector_minimum=node_voltage_magnitude_vector_minimum,
        node_voltage_magnitude_vector_maximum=node_voltage_magnitude_vector_maximum,
        branch_power_magnitude_vector_maximum=branch_power_magnitude_vector_maximum,
        kkt_conditions=False,
        grid_cost_coefficient=grid_cost_coefficient
    )

    # Define DER problem.

    # Solve centralized optimization problem.
    optimization_baseline.solve()

    results_non_strategic = mesmo.problems.Results()
    results_non_strategic.update(linear_electric_grid_model_set.get_optimization_results(optimization_baseline))
    results_non_strategic.update(
        linear_electric_grid_model_set.get_optimization_dlmps(optimization_baseline, price_data))
    results_non_strategic.update(der_model_set.get_optimization_results(optimization_baseline))

    # Obtain results.
    flexible_der_type = ['flexible_generator', 'flexible_load']
    seller_ders = pd.Index(
        [der_name for der_type, der_name in electric_grid_model.ders if 'fixed_generator' in der_type])
    buyer_ders = pd.Index([der_name for der_type, der_name in electric_grid_model.ders if 'fixed_load' in der_type])
    seller_dlmp = results_non_strategic.electric_grid_total_dlmp_der_active_power.loc[:, (slice(None), seller_ders)]
    buyer_dlmp = results_non_strategic.electric_grid_total_dlmp_der_active_power.loc[:, (slice(None), buyer_ders)]
    der_active_power_reference = pd.Series(der_model_set.der_active_power_vector_reference,
                                           index=der_model_set.electric_ders)
    seller_der_active_power_referecne = der_active_power_reference.loc[:, seller_ders]
    buyer_der_active_power_reference = der_active_power_reference.loc[:, buyer_ders]

    grid_using_price = pd.DataFrame(0, index=seller_dlmp.index,
                                    columns=pd.MultiIndex.from_product([seller_ders, buyer_ders]))
    for x, b in buyer_dlmp.columns:
        for y, s in seller_dlmp.columns:  # for y, b in grid_using_price.columns:
            grid_using_price.at[:, (s, b)] = buyer_dlmp.loc[:, (slice(None), b)].values - seller_dlmp.loc[:,
                                                                                          (slice(None), s)].values

    # buyer_ones = sp.block_diag([[np.ones(len(buyer_ders))]] * len(scenario_data.timesteps))
    # seller_ones = sp.block_diag([[np.ones(len(seller_ders))]] * len(scenario_data.timesteps)).transpose()
    # grid_using_price = -1.0 * seller_dlmp.transpose().values @ buyer_ones + seller_ones @ buyer_dlmp.values

    seller_optimization_problem_sets = pd.Series(data=None, index=seller_ders, dtype=object)
    for der_name in seller_optimization_problem_sets.index:
        seller_optimization_problem_sets.at[der_name] = mesmo.utils.OptimizationProblem()

        # Define seller's ADMM variable
        seller_optimization_problem_sets.loc[der_name].define_variable(
            f'energy_transacted_from_seller_{der_name}_to_buyers', buyer=buyer_ders, timestep=scenario_data.timesteps
        )
        seller_optimization_problem_sets.loc[der_name].define_variable(
            f'deviation_of_energy_transacted_from_seller_{der_name}_to_buyers', buyer=buyer_ders,
            timestep=scenario_data.timesteps
        )
        seller_optimization_problem_sets.loc[der_name].define_variable(
            f'seller_{der_name}_active_power_vector', timestep=scenario_data.timesteps
        )
        # Define seller's ADMMM parameter
        seller_optimization_problem_sets.loc[der_name].define_parameter(
            f'admm_lambda_seller_{der_name}_to_buyers_active_power',
            np.zeros(len(scenario_data.timesteps) * len(buyer_ders))
        )
        seller_optimization_problem_sets.loc[der_name].define_parameter(
            f'energy_transacted_from_seller_{der_name}_to_buyers_local_copy',
            np.zeros((len(scenario_data.timesteps) * len(buyer_ders), 1))
        )
        seller_optimization_problem_sets.loc[der_name].define_parameter(
            f'energy_transacted_from_seller_{der_name}_to_buyers_zeros',
            np.zeros((len(scenario_data.timesteps) * len(buyer_ders), 1))
        )
        seller_optimization_problem_sets.loc[der_name].define_parameter(
            f'seller_{der_name}_max_power',
            np.array([1.0] * len(scenario_data.timesteps))
        )
        seller_optimization_problem_sets.loc[der_name].define_parameter(
            f'seller_{der_name}_min_power',
            np.array([0.0] * len(scenario_data.timesteps))
        )
        seller_optimization_problem_sets.loc[der_name].define_parameter(
            f'half_of_grid_using_price_for_seller_{der_name}',
            pd.concat([grid_using_price.loc[i, (der_name, slice(None))] for i in grid_using_price.index]).values
        )
        seller_optimization_problem_sets.loc[der_name].define_parameter(
            f'buyer_sized_ones_for_{der_name}_energy_transaction',
            sp.block_diag([np.array([[1.0] * len(buyer_ders)])] * len(scenario_data.timesteps))
        )

    buyer_optimization_problem_sets = pd.Series(data=None, index=buyer_ders, dtype=object)
    for der_name in buyer_optimization_problem_sets.index:
        buyer_optimization_problem_sets.loc[der_name] = mesmo.utils.OptimizationProblem()

        # Define seller's ADMM variable
        buyer_optimization_problem_sets.loc[der_name].define_variable(
            f'energy_transacted_from_sellers_to_buyer_{der_name}', seller=seller_ders, timestep=scenario_data.timesteps
        )
        buyer_optimization_problem_sets.loc[der_name].define_variable(
            f'deviation_of_energy_transacted_from_sellers_to_buyer_{der_name}', seller=seller_ders,
            timestep=scenario_data.timesteps
        )
        buyer_optimization_problem_sets.loc[der_name].define_variable(
            f'buyer_{der_name}_active_power_vector', timestep=scenario_data.timesteps
        )
        # Define seller's ADMMM parameter
        buyer_optimization_problem_sets.loc[der_name].define_parameter(
            f'energy_transacted_from_sellers_to_buyer_{der_name}_local_copy',
            np.zeros((len(scenario_data.timesteps) * len(seller_ders), 1))
        )
        buyer_optimization_problem_sets.loc[der_name].define_parameter(
            f'admm_lambda_from_sellers_to_buyer_{der_name}_active_power',
            np.zeros(len(scenario_data.timesteps) * len(seller_ders))
        )
        buyer_optimization_problem_sets.loc[der_name].define_parameter(
            f'energy_transacted_from_sellers_to_buyer_{der_name}_zeros',
            np.zeros((len(scenario_data.timesteps) * len(seller_ders), 1))
        )
        buyer_optimization_problem_sets.loc[der_name].define_parameter(
            f'buyer_{der_name}_max_power',
            np.array([1.0] * len(scenario_data.timesteps))
        )
        buyer_optimization_problem_sets.loc[der_name].define_parameter(
            f'buyer_{der_name}_min_power',
            np.array([0.0] * len(scenario_data.timesteps))
        )
        buyer_optimization_problem_sets.loc[der_name].define_parameter(
            f'half_of_grid_using_price_for_buyer_{der_name}',
            pd.concat([grid_using_price.loc[i, (slice(None), der_name)] for i in grid_using_price.index]).values
        )
        buyer_optimization_problem_sets.loc[der_name].define_parameter(
            f'seller_sized_ones_for_{der_name}_energy_transaction',
            sp.block_diag([np.array([[1.0] * len(seller_ders)])] * len(scenario_data.timesteps))
        )
    while radius >= 1:
        # Defining optimization constraints and objectives for sellers:
        for der_name in seller_optimization_problem_sets.index:
            seller_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', f'buyer_sized_ones_for_{der_name}_energy_transaction',
                 dict(name=f'energy_transacted_from_seller_{der_name}_to_buyers')),
                '==',
                ('variable', seller_der_active_power_referecne.loc[:, der_name].values[0],
                 dict(name=f'seller_{der_name}_active_power_vector'))
            )
            seller_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', -1.0, dict(name=f'deviation_of_energy_transacted_from_seller_{der_name}_to_buyers')),
                '==',
                ('variable', -1.0, dict(name=f'energy_transacted_from_seller_{der_name}_to_buyers')),
                ('constant', f'energy_transacted_from_seller_{der_name}_to_buyers_local_copy')
            )
            seller_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', 1.0, dict(name=f'seller_{der_name}_active_power_vector')),
                '>=',
                ('constant', f'seller_{der_name}_min_power')
            )
            seller_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', 1.0, dict(name=f'seller_{der_name}_active_power_vector')),
                '<=',
                ('constant', f'seller_{der_name}_max_power')
            )
            seller_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', 1.0, dict(
                    name=f'energy_transacted_from_seller_{der_name}_to_buyers')),
                '>=',
                ('constant', f'energy_transacted_from_seller_{der_name}_to_buyers_zeros')
            )
            seller_optimization_problem_sets.loc[der_name].define_objective(
                ('variable', f'half_of_grid_using_price_for_seller_{der_name}',
                 dict(name=f'energy_transacted_from_seller_{der_name}_to_buyers')),
                ('variable', f'admm_lambda_seller_{der_name}_to_buyers_active_power',
                 dict(name=f'deviation_of_energy_transacted_from_seller_{der_name}_to_buyers')),
                ('variable', 0.5 * admm_rho, dict(name=f'deviation_of_energy_transacted_from_seller_{der_name}_to_buyers'),
                 dict(name=f'deviation_of_energy_transacted_from_seller_{der_name}_to_buyers'))
            )
            seller_optimization_problem_sets.loc[der_name].solve()

        # Defining optimization constraints and objectives for sellers:
        for der_name in buyer_optimization_problem_sets.index:
            buyer_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', f'seller_sized_ones_for_{der_name}_energy_transaction',
                 dict(name=f'energy_transacted_from_sellers_to_buyer_{der_name}')),
                '==',
                ('variable', -1.0 * buyer_der_active_power_reference.loc[:, der_name].values[0],
                 dict(name=f'buyer_{der_name}_active_power_vector'))
            )
            buyer_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', -1.0, dict(name=f'deviation_of_energy_transacted_from_sellers_to_buyer_{der_name}')),
                '==',
                ('variable', -1.0, dict(name=f'energy_transacted_from_sellers_to_buyer_{der_name}')),
                ('constant', f'energy_transacted_from_sellers_to_buyer_{der_name}_local_copy'),
            )
            buyer_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', 1.0, dict(name=f'buyer_{der_name}_active_power_vector')),
                '>=',
                ('constant', f'buyer_{der_name}_min_power')
            )
            buyer_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', 1.0, dict(name=f'buyer_{der_name}_active_power_vector')),
                '<=',
                ('constant', f'buyer_{der_name}_max_power')
            )
            buyer_optimization_problem_sets.loc[der_name].define_constraint(
                ('variable', 1.0, dict(
                    name=f'energy_transacted_from_sellers_to_buyer_{der_name}')),
                '>=',
                ('constant', f'energy_transacted_from_sellers_to_buyer_{der_name}_zeros')
            )
            buyer_optimization_problem_sets.loc[der_name].define_objective(
                ('variable', f'half_of_grid_using_price_for_buyer_{der_name}',
                 dict(name=f'energy_transacted_from_sellers_to_buyer_{der_name}')),
                ('variable', f'admm_lambda_from_sellers_to_buyer_{der_name}_active_power',
                 dict(name=f'deviation_of_energy_transacted_from_sellers_to_buyer_{der_name}')),
                ('variable', 0.5 * admm_rho, dict(name=f'deviation_of_energy_transacted_from_sellers_to_buyer_{der_name}'),
                 dict(name=f'deviation_of_energy_transacted_from_sellers_to_buyer_{der_name}'))
            )
            buyer_optimization_problem_sets.loc[der_name].solve()

        # Update admm parameters for seller optimization:
        for seller in seller_optimization_problem_sets.index:
            seller_optimization_problem_sets.loc[seller].parameters[
                f'energy_transacted_from_seller_{seller}_to_buyers_local_copy'] = 0.5 * np.transpose([
                pd.concat([
                    seller_optimization_problem_sets.loc[seller].results[
                        f'energy_transacted_from_seller_{seller}_to_buyers'][buyer] for buyer in buyer_ders
                ]).values + pd.concat([
                    buyer_optimization_problem_sets.loc[buyer].results[
                        f'energy_transacted_from_sellers_to_buyer_{buyer}'][seller] for buyer in buyer_ders]).values
            ])

            seller_optimization_problem_sets.loc[seller].parameters[
                f'admm_lambda_seller_{seller}_to_buyers_active_power'] += admm_rho * (pd.concat([
                    seller_optimization_problem_sets.loc[seller].results[
                        f'energy_transacted_from_seller_{seller}_to_buyers'][buyer] for buyer in buyer_ders
                ]).values - seller_optimization_problem_sets.loc[seller].parameters[
                            f'energy_transacted_from_seller_{seller}_to_buyers_local_copy'].ravel())

        # Update admm parameters for buyer optimization:
        for buyer in buyer_optimization_problem_sets.index:
            buyer_optimization_problem_sets.loc[buyer].parameters[
                f'energy_transacted_from_sellers_to_buyer_{buyer}_local_copy'] = 0.5 * np.transpose([
                pd.concat([
                    buyer_optimization_problem_sets.loc[buyer].results[
                        f'energy_transacted_from_sellers_to_buyer_{buyer}'][seller] for seller in seller_ders
                ]).values + pd.concat([
                    seller_optimization_problem_sets.loc[seller].results[
                        f'energy_transacted_from_seller_{seller}_to_buyers'][buyer] for seller in seller_ders]).values
            ])

            buyer_optimization_problem_sets.loc[buyer].parameters[
                f'admm_lambda_from_sellers_to_buyer_{buyer}_active_power'] += admm_rho * (pd.concat([
                    buyer_optimization_problem_sets.loc[buyer].results[
                        f'energy_transacted_from_sellers_to_buyer_{buyer}'][seller] for seller in seller_ders
                ]).values - buyer_optimization_problem_sets.loc[buyer].parameters[
                            f'energy_transacted_from_sellers_to_buyer_{buyer}_local_copy'].ravel())

        radius = np.linalg.norm(a=np.concatenate(a=[seller_optimization_problem_sets.loc[seller].results[
                f'deviation_of_energy_transacted_from_seller_{seller}_to_buyers'] for seller in seller_ders]).ravel())

        print(radius)


    print(2)


if __name__ == '__main__':
    main()