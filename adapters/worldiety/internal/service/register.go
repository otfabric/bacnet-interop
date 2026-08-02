// SPDX-License-Identifier: MIT

package service

import (
	"github.com/worldiety/bacnet/apdu"
)

// Register installs confirmed and unconfirmed service handlers on the ASE.
func (s *Server) Register() error {
	if err := s.ASE.RegisterUnconfirmed(apdu.ServiceChoiceWhoIs, s.handleWhoIs); err != nil {
		return err
	}
	if err := s.ASE.RegisterUnconfirmed(apdu.ServiceChoiceWhoHas, s.handleWhoHas); err != nil {
		return err
	}
	if err := s.ASE.RegisterConfirmed(apdu.ServiceChoiceReadProperty, s.handleReadProperty); err != nil {
		return err
	}
	if err := s.ASE.RegisterConfirmed(apdu.ServiceChoiceReadPropertyMultiple, s.handleReadPropertyMultiple); err != nil {
		return err
	}
	if err := s.ASE.RegisterConfirmed(apdu.ServiceChoiceWriteProperty, s.handleWriteProperty); err != nil {
		return err
	}
	if err := s.ASE.RegisterConfirmed(apdu.ServiceChoiceWritePropertyMultiple, s.handleWritePropertyMultiple); err != nil {
		return err
	}
	if err := s.ASE.RegisterConfirmed(apdu.ServiceChoiceReadRange, s.handleReadRange); err != nil {
		return err
	}
	return nil
}
