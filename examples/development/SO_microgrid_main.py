"""Example script for DRO problem."""

import cvxpy as cp
import numpy as np
import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

import fledge
from mg_offer_stage_1_problem_standard_form import stage_1_problem_standard_form
from mg_offer_stage_2_problem_standard_form import stage_2_problem_standard_form
from mg_offer_stage_3_problem_standard_form import stage_3_problem_standard_form
from dro_data_interface import DRO_data, DRO_ambiguity_set


class scenario_generation(object):
    delta: np.array
    probability: np.array


    def __init__(
            self,
            scenario_number: int,
            scenario_name: str,
            standard_form_stage_2: fledge.utils.StandardForm,
            delta_indices_stage2: float,
            dro_data_set: DRO_data
    ):

        number_of_uncertainties = len(delta_indices_stage2)

        self.delta = np.zeros((number_of_uncertainties, scenario_number))

        self.probability = np.zeros((1, scenario_number))

        der_model_set = fledge.der_models.DERModelSet(scenario_name)

        linear_electric_grid_model = fledge.electric_grid_models.LinearElectricGridModelGlobal(scenario_name)


        temp_indices = fledge.utils.get_index(
            standard_form_stage_2.variables, name='uncertainty_energy_price_deviation_s2',
            timestep=linear_electric_grid_model.electric_grid_model.timesteps
        )

        for index_time in temp_indices:
            self.delta[np.where(pd.Index(delta_indices_stage2).isin([index_time])),:] \
                = np.random.normal(0, dro_data_set.variance_energy_price, scenario_number)

        temp_indices = fledge.utils.get_index(
            standard_form_stage_2.variables, name='uncertainty_up_reserve_price_deviation_s2',
            timestep=linear_electric_grid_model.electric_grid_model.timesteps
        )

        for index_time in temp_indices:
            self.delta[np.where(pd.Index(delta_indices_stage2).isin([index_time])),:] = \
                np.random.normal(0, dro_data_set.variance_contingency_price, scenario_number)

        temp_indices = fledge.utils.get_index(
            standard_form_stage_2.variables, name='uncertainty_down_reserve_price_deviation_s2',
            timestep=linear_electric_grid_model.electric_grid_model.timesteps
        )

        for index_time in temp_indices:
            self.delta[np.where(pd.Index(delta_indices_stage2).isin([index_time])), :] = \
                np.random.normal(0, dro_data_set.variance_contingency_price, scenario_number)


        for der_name, der_model in der_model_set.flexible_der_models.items():
            if not der_model.disturbances.empty:
                temp_indices = fledge.utils.get_index(
                    standard_form_stage_2.variables, name='uncertainty_disturbances_vector_s2',
                    timestep=der_model.timesteps, der_name=[der_model.der_name],
                    disturbance=der_model.disturbances,
                )

                for index_time in temp_indices:
                    self.delta[np.where(pd.Index(delta_indices_stage2).isin([index_time])),:] = \
                        np.random.normal(0, 20, scenario_number)

        self.probability[:,:] = 1/scenario_number

def main():
    scenario_name = 'singapore_6node_custom'
    # scenario_name = 'singapore_6node'

    price_categories = ['energy', 'up_reserve', 'down_reserve']
    ambiguity_set_dual_variables_categories = ['mu_1', 'nu_1', 'mu_2', 'nu_2', 'mu_3', 'nu_3', 'mu_4', 'nu_4']

    # Get results path.
    results_path = fledge.utils.get_results_path(__file__, scenario_name)

    fledge.data_interface.recreate_database()

    price_data = fledge.data_interface.PriceData(scenario_name)

    dro_data_set = DRO_data("C:\\Users\\kai.zhang\\Desktop\\local_fledge_data\\dro_data\\")

    # initialize all three stage problem
    standard_form_stage_1, A1_matrix, b1_vector, f_vector, stochastic_scenarios, der_model_set \
        = stage_1_problem_standard_form(scenario_name, dro_data_set)

    standard_form_stage_2, b2_vector, A2_matrix, B2_matrix, C2_matrix, M_Q2_delta, m_Q2_s2, s2_indices_stage2, \
        delta_indices_stage2, s1_indices = stage_2_problem_standard_form(scenario_name, dro_data_set)

    standard_form_stage_3, b3_vector, A3_matrix, B3_matrix, C3_matrix, D3_matrix, m_Q3_s2, m_Q3_s3, \
        delta_indices_stage3, s1_indices_stage3, s2_indices_stage3, s3_indices_stage3 = \
        stage_3_problem_standard_form(scenario_name, dro_data_set)

    # Instantiate optimization problem.
    optimization_problem_dro = fledge.utils.OptimizationProblem()

    print('SO form')

    scenario_number = 1000
    optimization_problem_SO = fledge.utils.OptimizationProblem()
    # Define optimization problem.
    optimization_problem_SO.s_1 = cp.Variable((len(s1_indices_stage3), 1))
    optimization_problem_SO.s_2 = cp.Variable((len(s2_indices_stage3), scenario_number))
    optimization_problem_SO.s_3 = cp.Variable((len(s3_indices_stage3), scenario_number))
    optimization_problem_SO.delta = cp.Variable((len(delta_indices_stage3), scenario_number))

    scenario_uncertainty = scenario_generation(scenario_number, scenario_name, standard_form_stage_2, delta_indices_stage2, dro_data_set)


    # optimization_problem_SO.constraints.append(
    #     optimization_problem_SO.delta == scenario_uncertainty.delta
    # )
    optimization_problem_SO.delta = scenario_uncertainty.delta

    optimization_problem_SO.constraints.append(
        A1_matrix.toarray() @ optimization_problem_SO.s_1 <= b1_vector
    )

    optimization_problem_SO.objective -= (
        (
                f_vector.T
                @ optimization_problem_SO.s_1
        )
    )

    for scenario_index in range(scenario_number):
        optimization_problem_SO.constraints.append(
            A2_matrix.toarray() @ optimization_problem_SO.s_1 + B2_matrix.toarray() @ optimization_problem_SO.s_2[:,[scenario_index]]
            + C2_matrix @ optimization_problem_SO.delta[:,[scenario_index]] <= b2_vector
        )

        optimization_problem_SO.constraints.append(
            A3_matrix.toarray() @ optimization_problem_SO.s_1 + B3_matrix.toarray() @ optimization_problem_SO.s_2[:,[scenario_index]]
            + C3_matrix @ optimization_problem_SO.delta[:,[scenario_index]] + D3_matrix.toarray() @ optimization_problem_SO.s_3[:,[scenario_index]]
            <= b3_vector
        )

        optimization_problem_SO.objective -= scenario_uncertainty.probability[:, scenario_index]*(
            (
                optimization_problem_SO.s_1.T @ M_Q2_delta @ optimization_problem_SO.delta[:,[scenario_index]]
            ) +
            (
                    m_Q2_s2.T @ optimization_problem_SO.s_2[:,[scenario_index]]
            )
        )

        optimization_problem_SO.objective -= scenario_uncertainty.probability[:, scenario_index]*(
            (
                    m_Q3_s2.T @ optimization_problem_SO.s_2[:,[scenario_index]]
            ) +
            (
                    m_Q3_s3.T @ optimization_problem_SO.s_3[:,[scenario_index]]
            )
        )



    optimization_problem_SO.solve()

    print()


    #
    # # Obtain results.
    # results_determinstic = standard_form_stage_1.get_results(optimization_problem_deterministic.x_vector)
    #
    # # Obtain reserve results.
    # no_reserve_det = pd.Series(results_determinstic['energy'].values.ravel(), index=der_model_set.timesteps)
    # up_reserve_det = pd.Series(results_determinstic['up_reserve'].values.ravel(), index=der_model_set.timesteps)
    # down_reserve_det = pd.Series(results_determinstic['down_reserve'].values.ravel(), index=der_model_set.timesteps)
    #
    # for variable_name in results_determinstic:
    #     results_determinstic[variable_name].to_csv(os.path.join(results_path, f'{variable_name}_det.csv'))
    #
    # objective_det = pd.DataFrame(optimization_problem_deterministic.objective.value, columns = ['objective_value_det'])
    #
    # objective_det.to_csv(os.path.join(results_path, f'objective_det.csv'))
    #
    # # Plot some results.
    # figure = go.Figure()
    # figure.add_scatter(
    #     x=no_reserve.index,
    #     y=no_reserve.values,
    #     name='energy_offer_dro',
    #     line=go.scatter.Line(shape='hv', width=9, dash='dot')
    # )
    # figure.add_scatter(
    #     x=up_reserve.index,
    #     y=up_reserve.values,
    #     name='up_reserve_offer_dro',
    #     line=go.scatter.Line(shape='hv', width=8, dash='dot')
    # )
    # figure.add_scatter(
    #     x=down_reserve.index,
    #     y=down_reserve.values,
    #     name='down_reserve_offer_dro',
    #     line=go.scatter.Line(shape='hv', width=7, dash='dot')
    # )
    #
    # figure.add_scatter(
    #     x=no_reserve_det.index,
    #     y=no_reserve_det.values,
    #     name='energy_offer_determinstic',
    #     line=go.scatter.Line(shape='hv', width=6, dash='dot')
    # )
    # figure.add_scatter(
    #     x=up_reserve_det.index,
    #     y=up_reserve_det.values,
    #     name='up_reserve_offer_determinstic',
    #     line=go.scatter.Line(shape='hv', width=5, dash='dot')
    # )
    # figure.add_scatter(
    #     x=down_reserve_det.index,
    #     y=down_reserve_det.values,
    #     name='down_reserve_offer_determinstic',
    #     line=go.scatter.Line(shape='hv', width=4, dash='dot')
    # )
    #
    # figure.add_scatter(
    #     x=up_reserve.index,
    #     y=(no_reserve + up_reserve).values,
    #     name='no_reserve + up_reserve',
    #     line=go.scatter.Line(shape='hv', width=3, dash='dot')
    # )
    # figure.add_scatter(
    #     x=up_reserve.index,
    #     y=(no_reserve - down_reserve).values,
    #     name='no_reserve - down_reserve',
    #     line=go.scatter.Line(shape='hv', width=2, dash='dot')
    # )
    # figure.update_layout(
    #     title=f'Power balance',
    #     xaxis=go.layout.XAxis(tickformat='%H:%M'),
    #     legend=go.layout.Legend(x=0.01, xanchor='auto', y=0.99, yanchor='auto')
    # )
    # # figure.show()
    # fledge.utils.write_figure_plotly(figure, os.path.join(results_path, f'0_power_balance'))
    #
    # for der_name, der_model in der_model_set.flexible_der_models.items():
    #
    #     for output in der_model.outputs:
    #         figure = go.Figure()
    #         figure.add_scatter(
    #             x=der_model.output_maximum_timeseries.index,
    #             y=der_model.output_maximum_timeseries.loc[:, output].values,
    #             name='Maximum bound',
    #             line=go.scatter.Line(shape='hv')
    #         )
    #         figure.add_scatter(
    #             x=der_model.output_minimum_timeseries.index,
    #             y=der_model.output_minimum_timeseries.loc[:, output].values,
    #             name='Minimum bound',
    #             line=go.scatter.Line(shape='hv')
    #         )
    #         for number, stochastic_scenario in enumerate(stochastic_scenarios):
    #             if number == 0:
    #                 figure.add_scatter(
    #                     x=output_vector[stochastic_scenario].index,
    #                     y=output_vector[stochastic_scenario].loc[:, (der_name, output)].values,
    #                     name=f'optimal value in {stochastic_scenario} scenario',
    #                     line=go.scatter.Line(shape='hv', width=number + 5)
    #                 )
    #             elif number == 1:
    #                 figure.add_scatter(
    #                     x=output_vector[stochastic_scenario].index,
    #                     y=output_vector[stochastic_scenario].loc[:, (der_name, output)].values,
    #                     name=f'optimal value in {stochastic_scenario} scenario',
    #                     line=go.scatter.Line(shape='hv', width=number + 4, dash='dashdot')
    #                 )
    #             else:
    #                 figure.add_scatter(
    #                     x=output_vector[stochastic_scenario].index,
    #                     y=output_vector[stochastic_scenario].loc[:, (der_name, output)].values,
    #                     name=f'optimal value in {stochastic_scenario} scenario',
    #                     line=go.scatter.Line(shape='hv', width=number + 3, dash='dot')
    #                 )
    #         figure.update_layout(
    #             title=f'DER: ({der_model.der_type}, {der_name}) / Output: {output}',
    #             xaxis=go.layout.XAxis(tickformat='%H:%M'),
    #             legend=go.layout.Legend(x=0.01, xanchor='auto', y=0.99, yanchor='auto')
    #         )
    #         # figure.show()
    #         fledge.utils.write_figure_plotly(figure, os.path.join(
    #             results_path, f'der_{der_model.der_type}_{der_name}_output_{output}'
    #         ))

    #
    # for der_name, der_model in der_model_set.flexible_der_models.items():
    #
    #     for output in der_model.outputs:
    #         figure = go.Figure()
    #         figure.add_scatter(
    #             x=der_model.output_maximum_timeseries.index,
    #             y=der_model.output_maximum_timeseries.loc[:, output].values,
    #             name='Maximum',
    #             line=go.scatter.Line(shape='hv')
    #         )
    #         figure.add_scatter(
    #             x=der_model.output_minimum_timeseries.index,
    #             y=der_model.output_minimum_timeseries.loc[:, output].values,
    #             name='Minimum',
    #             line=go.scatter.Line(shape='hv')
    #         )
    #         for number, stochastic_scenario in enumerate(stochastic_scenarios):
    #             figure.add_scatter(
    #                 x=output_vector[stochastic_scenario].index,
    #                 y=output_vector[stochastic_scenario].loc[:, (der_name, output)].values,
    #                 name=f'Optimal: {stochastic_scenario}',
    #                 line=go.scatter.Line(shape='hv', width=number + 3, dash='dot')
    #             )
    #         figure.update_layout(
    #             title=f'DER: ({der_model.der_type}, {der_name}) / Output: {output}',
    #             xaxis=go.layout.XAxis(tickformat='%H:%M'),
    #             legend=go.layout.Legend(x=0.01, xanchor='auto', y=0.99, yanchor='auto')
    #         )
    #         # figure.show()
    #         fledge.utils.write_figure_plotly(figure, os.path.join(
    #             results_path, f'der_{der_model.der_type}_{der_name}_output_{output}'
    #         ))

        # for control in der_model.controls:
        #     figure = go.Figure()
        #     for number, stochastic_scenario in enumerate(stochastic_scenarios):
        #         figure.add_scatter(
        #             x=output_vector[stochastic_scenario].index,
        #             y=output_vector[stochastic_scenario].loc[:, (der_name, control)].values,
        #             name=f'Optimal: {stochastic_scenario}',
        #             line=go.scatter.Line(shape='hv', width=number+3, dash='dot')
        #         )
        #     figure.update_layout(
        #         title=f'DER: ({der_model.der_type}, {der_name}) / Control: {control}',
        #         xaxis=go.layout.XAxis(tickformat='%H:%M'),
        #         legend=go.layout.Legend(x=0.01, xanchor='auto', y=0.99, yanchor='auto')
        #     )
        #     # figure.show()
        #     fledge.utils.write_figure_plotly(figure, os.path.join(
        #         results_path, f'der_{der_model.der_type}_{der_name}_control_{control}'
        #     ))

        # for disturbance in der_model.disturbances:
        #     figure = go.Figure()
        #     figure.add_scatter(
        #         x=der_model.disturbance_timeseries.index,
        #         y=der_model.disturbance_timeseries.loc[:, disturbance].values,
        #         line=go.scatter.Line(shape='hv')
        #     )
        #     figure.update_layout(
        #         title=f'DER: ({der_model.der_type}, {der_name}) / Disturbance: {disturbance}',
        #         xaxis=go.layout.XAxis(tickformat='%H:%M'),
        #         showlegend=False
        #     )
        #     # figure.show()
        #     fledge.utils.write_figure_plotly(figure, os.path.join(
        #         results_path, f'der_{der_model.der_type}_{der_name}_disturbance_{disturbance}'
        #     ))

    for commodity_type in ['active_power', 'reactive_power']:

        if commodity_type in price_data.price_timeseries.columns.get_level_values('commodity_type'):
            figure = go.Figure()
            figure.add_scatter(
                x=price_data.price_timeseries.index,
                y=price_data.price_timeseries.loc[:, (commodity_type, 'source', 'source')].values,
                line=go.scatter.Line(shape='hv')
            )
            figure.update_layout(
                title=f'Price: {commodity_type}',
                xaxis=go.layout.XAxis(tickformat='%H:%M')
            )
            # figure.show()
            fledge.utils.write_figure_plotly(figure, os.path.join(results_path, f'price_{commodity_type}'))

    # Print results path.
    fledge.utils.launch(results_path)
    print(f"Results are stored in: {results_path}")



if __name__ == '__main__':
    main()
