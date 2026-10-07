# Протокол автоматизированного тестирования ProjectFlow

* Дата и время запуска: 07.10.2026 14:54:39
* Версия Python: 3.12.14
* Платформа: Windows-11-10.0.26300-SP0
* Команда запуска: `python -m tools.run_tests`

## Итоговые показатели

| Показатель | Значение |
|---|---|
| Всего тестов | 85 |
| Пройдено | 85 |
| Не пройдено | 0 |
| Ошибок выполнения | 0 |
| Пропущено | 0 |
| Доля успешных | 100.0 % |

## Результаты по тестовым модулям

| Тестовый модуль | Всего | Пройдено | Не пройдено | Ошибок | Пропущено |
|---|---|---|---|---|---|
| `test_auth_module` | 17 | 17 | 0 | 0 | 0 |
| `test_integration` | 34 | 34 | 0 | 0 | 0 |
| `test_report_module` | 13 | 13 | 0 | 0 | 0 |
| `test_task_module` | 21 | 21 | 0 | 0 | 0 |

## Перечень выполненных тестов

| № | Тест | Результат | Время, с |
|---|---|---|---|
| 1 | `test_auth_module::test_register_user_success` | пройден | 0.061 |
| 2 | `test_auth_module::test_register_user_duplicate_username` | пройден | 0.060 |
| 3 | `test_auth_module::test_register_user_weak_password` | пройден | 0.012 |
| 4 | `test_auth_module::test_register_user_invalid_email` | пройден | 0.012 |
| 5 | `test_auth_module::test_login_user_success` | пройден | 0.121 |
| 6 | `test_auth_module::test_login_user_wrong_password` | пройден | 0.106 |
| 7 | `test_auth_module::test_login_user_nonexistent` | пройден | 0.011 |
| 8 | `test_auth_module::test_refresh_access_token_success` | пройден | 0.106 |
| 9 | `test_auth_module::test_refresh_access_token_invalid` | пройден | 0.010 |
| 10 | `test_auth_module::test_request_password_reset_success` | пройден | 0.060 |
| 11 | `test_auth_module::test_request_password_reset_nonexistent_email` | пройден | 0.011 |
| 12 | `test_auth_module::test_reset_password_success` | пройден | 0.151 |
| 13 | `test_auth_module::test_get_user_by_id_success` | пройден | 0.057 |
| 14 | `test_auth_module::test_get_user_by_id_nonexistent` | пройден | 0.011 |
| 15 | `test_auth_module::test_update_user_role_success` | пройден | 0.105 |
| 16 | `test_auth_module::test_update_user_role_insufficient_permissions` | пройден | 0.105 |
| 17 | `test_auth_module::test_deactivate_user_success` | пройден | 0.105 |
| 18 | `test_integration::test_user_creates_task_and_task_appears_in_report` | пройден | 0.151 |
| 19 | `test_integration::test_auth_token_accepted_by_all_modules` | пройден | 0.197 |
| 20 | `test_integration::test_role_based_access_control` | пройден | 0.149 |
| 21 | `test_integration::test_status_change_is_reflected_in_report` | пройден | 0.155 |
| 22 | `test_integration::test_status_history_is_recorded_for_reporting` | пройден | 0.155 |
| 23 | `test_integration::test_multi_user_report_workflow` | пройден | 0.152 |
| 24 | `test_integration::test_all_model_transitions_are_implemented` | пройден | 0.152 |
| 25 | `test_integration::test_no_extra_transitions_in_implementation` | пройден | 0.152 |
| 26 | `test_integration::test_transition_matrix_is_complete` | пройден | 0.161 |
| 27 | `test_integration::test_transition_new_to_in_progress` | пройден | 0.167 |
| 28 | `test_integration::test_transition_new_to_rejected` | пройден | 0.155 |
| 29 | `test_integration::test_transition_in_progress_to_review` | пройден | 0.160 |
| 30 | `test_integration::test_transition_in_progress_to_rejected` | пройден | 0.156 |
| 31 | `test_integration::test_transition_review_to_completed` | пройден | 0.155 |
| 32 | `test_integration::test_transition_review_to_in_progress` | пройден | 0.155 |
| 33 | `test_integration::test_transition_rejected_to_new` | пройден | 0.153 |
| 34 | `test_integration::test_transition_completed_to_in_progress` | пройден | 0.153 |
| 35 | `test_integration::test_invalid_transitions_are_blocked` | пройден | 0.163 |
| 36 | `test_integration::test_transition_roles_are_declared` | пройден | 0.155 |
| 37 | `test_integration::test_implementation_matches_state_model` | пройден | 0.155 |
| 38 | `test_integration::test_deleted_tasks_are_terminal` | пройден | 0.155 |
| 39 | `test_integration::test_api_health_endpoint` | пройден | 0.576 |
| 40 | `test_integration::test_api_full_workflow_over_http` | пройден | 0.653 |
| 41 | `test_integration::test_api_requires_authentication` | пройден | 0.523 |
| 42 | `test_integration::test_api_rejects_invalid_token` | пройден | 0.522 |
| 43 | `test_integration::test_api_validates_payload` | пройден | 0.628 |
| 44 | `test_integration::test_api_unknown_route_returns_404` | пройден | 0.521 |
| 45 | `test_integration::test_api_method_not_allowed` | пройден | 0.521 |
| 46 | `test_integration::test_api_pdf_export_produces_valid_document` | пройден | 0.640 |
| 47 | `test_integration::test_api_excel_export_produces_valid_document` | пройден | 1.152 |
| 48 | `test_integration::test_report_by_period_covers_all_projects` | пройден | 0.156 |
| 49 | `test_integration::test_report_saved_to_database` | пройден | 0.153 |
| 50 | `test_integration::test_authentication_error_for_wrong_credentials` | пройден | 0.189 |
| 51 | `test_integration::test_shared_database_between_modules` | пройден | 0.157 |
| 52 | `test_report_module::test_generate_report_by_user_success` | пройден | 0.104 |
| 53 | `test_report_module::test_generate_report_by_user_with_date_filter` | пройден | 0.103 |
| 54 | `test_report_module::test_generate_report_by_user_nonexistent` | пройден | 0.103 |
| 55 | `test_report_module::test_generate_report_by_project_success` | пройден | 0.104 |
| 56 | `test_report_module::test_generate_report_by_project_statistics` | пройден | 0.103 |
| 57 | `test_report_module::test_generate_report_by_project_nonexistent` | пройден | 0.102 |
| 58 | `test_report_module::test_generate_report_by_period_success` | пройден | 0.106 |
| 59 | `test_report_module::test_generate_report_by_period_statistics` | пройден | 0.109 |
| 60 | `test_report_module::test_export_report_to_excel_success` | пройден | 0.122 |
| 61 | `test_report_module::test_export_report_to_pdf_success` | пройден | 0.115 |
| 62 | `test_report_module::test_get_reports_list_success` | пройден | 0.106 |
| 63 | `test_report_module::test_get_reports_list_filtered_by_user` | пройден | 0.112 |
| 64 | `test_report_module::test_integration_full_report_workflow` | пройден | 0.108 |
| 65 | `test_task_module::test_create_task_success` | пройден | 0.157 |
| 66 | `test_task_module::test_create_task_without_assignee` | пройден | 0.148 |
| 67 | `test_task_module::test_create_task_invalid_project` | пройден | 0.149 |
| 68 | `test_task_module::test_create_task_invalid_priority` | пройден | 0.152 |
| 69 | `test_task_module::test_get_task_by_id_success` | пройден | 0.154 |
| 70 | `test_task_module::test_get_task_by_id_nonexistent` | пройден | 0.154 |
| 71 | `test_task_module::test_get_tasks_filtered_by_project` | пройден | 0.155 |
| 72 | `test_task_module::test_get_tasks_filtered_by_assignee` | пройден | 0.157 |
| 73 | `test_task_module::test_update_task_success` | пройден | 0.148 |
| 74 | `test_task_module::test_update_task_insufficient_permissions` | пройден | 0.196 |
| 75 | `test_task_module::test_change_task_status_success` | пройден | 0.153 |
| 76 | `test_task_module::test_change_task_status_invalid_transition` | пройден | 0.156 |
| 77 | `test_task_module::test_change_task_status_from_completed` | пройден | 0.157 |
| 78 | `test_task_module::test_assign_task_success` | пройден | 0.170 |
| 79 | `test_task_module::test_assign_task_insufficient_permissions` | пройден | 0.152 |
| 80 | `test_task_module::test_delete_task_success` | пройден | 0.150 |
| 81 | `test_task_module::test_delete_task_insufficient_permissions` | пройден | 0.197 |
| 82 | `test_task_module::test_get_task_history` | пройден | 0.151 |
| 83 | `test_task_module::test_status_transitions_coverage` | пройден | 0.000 |
| 84 | `test_task_module::test_completed_task_cannot_return_to_new` | пройден | 0.000 |
| 85 | `test_task_module::test_review_cannot_be_rejected_directly` | пройден | 0.000 |

Неуспешных тестов нет: все проверки пройдены.

## Заключение

Все 85 автоматических проверок пройдены успешно. Результат признаётся положительным.
